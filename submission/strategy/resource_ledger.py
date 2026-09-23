"""Authoritative Multi-Resource Commitment Ledger.

Part of the SW-First Forward Architecture Redesign (Phase A).
Provides time-indexed accounting across future hours/days for:
1. Cash (HARD, CONSERVATIVE, SPECULATIVE inflow categories; zero double-reservation)
2. Feed (Physical accessibility, strict harvest causality, daily animal liabilities)
3. Market Orders (Engine-exact 10-order cap with command-specific slot costs)
4. Storage (Sequential execution: harvest -> carrier -> shed -> market -> midnight drop -> discard)
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class InflowConfidence(str, Enum):
    """Classification of future cash inflows."""
    HARD = "HARD"                  # Mechanically settled cash in farm wallet
    CONSERVATIVE = "CONSERVATIVE"  # Physically harvested inventory in shed/carriers at floor/drip price
    SPECULATIVE = "SPECULATIVE"    # In-ground crops, unlaid eggs, uncollected wool, future model projections


@dataclass
class DatedCashLiability:
    """A dated monetary obligation."""
    day: int
    hour: int
    amount: float
    purpose: str
    is_hard: bool = True           # Hard = feed/land/mandatory hires; Soft = discretionary investments


@dataclass
class DatedCashInflow:
    """An anticipated future cash inflow."""
    day: int
    hour: int
    amount: float
    confidence: InflowConfidence
    source: str


@dataclass
class DatedFeedLiability:
    """Daily feed requirement for an animal."""
    day: int
    hour_deadline: int             # Must be fed before hour 23
    animal_pos: Tuple[int, int]
    species: str
    amount: int = 1


@dataclass
class InGroundWheatHarvest:
    """Dated wheat harvest event."""
    day: int
    hour: int
    tile_pos: Tuple[int, int]
    expected_yield: int


@dataclass
class MarketSlotAllocation:
    """Reservation of market order capacity (10 max per turn)."""
    command_type: str              # HIRE, BUY_PRODUCT, BUY_LAND, BUY_ANIMAL, SELL
    slots_consumed: int
    details: Dict[str, Any] = field(default_factory=dict)


class ResourceLedger:
    """Authoritative, unified multi-resource ledger."""

    def __init__(self, current_day: int = 0, current_hour: int = 0) -> None:
        self.day: int = current_day
        self.hour: int = current_hour

        # Cash Ledger
        self.cash_on_hand: float = 0.0
        self.safety_reserve: float = 300.0
        self.dated_liabilities: List[DatedCashLiability] = []
        self.dated_inflows: List[DatedCashInflow] = []

        # Feed Ledger
        self.shed_wheat: int = 0
        self.worker_carried_wheat: int = 0
        self.in_ground_wheat: List[InGroundWheatHarvest] = []
        self.feed_liabilities: List[DatedFeedLiability] = []

        # Market Order Ledger
        # Maps (day, hour) -> list of allocated slots (max 10 total slots per turn)
        self.turn_order_allocations: Dict[Tuple[int, int], List[MarketSlotAllocation]] = {}

        # Storage Ledger
        self.shed_capacity: int = 100
        self.current_shed_occupancy: int = 0
        self.current_worker_carried_units: int = 0

    def update_from_observation(self, ctx: Dict[str, Any]) -> None:
        """Synchronize ledger with ground-truth engine observation."""
        self.day = ctx.get("day", 0)
        self.hour = ctx.get("hour", 0)
        farm = ctx.get("farm")
        private = ctx.get("private")

        # Cash
        self.cash_on_hand = float(getattr(farm, "money", 0.0)) if farm else 0.0

        # Feed & Storage
        shed_dict = getattr(private, "shed", {}) if private else {}
        self.shed_wheat = int(shed_dict.get("WHEAT", 0))
        self.current_shed_occupancy = sum(int(v) for v in shed_dict.values())

        carried_wheat = 0
        carried_total = 0
        inventories = getattr(private, "inventories", []) if private else []
        for inv in inventories:
            if isinstance(inv, dict):
                carried_wheat += int(inv.get("WHEAT", 0))
                carried_total += sum(int(v) for v in inv.values())
        self.worker_carried_wheat = carried_wheat
        self.current_worker_carried_units = carried_total

        # In-ground wheat tracking
        self.in_ground_wheat.clear()
        if farm:
            for t in farm.iter_tiles():
                if getattr(t, "kind", None) == "PLANT" and getattr(t, "crop", None) == "WHEAT":
                    # Wheat takes 4 days to reach max yield (or 2 for first yield)
                    age = getattr(t, "age", 0)
                    rem_days = max(0, 4 - age)
                    h_day = self.day + rem_days
                    if h_day < 30:
                        self.in_ground_wheat.append(
                            InGroundWheatHarvest(
                                day=h_day,
                                hour=0,  # harvests typically targeted in morning
                                tile_pos=t.pos if hasattr(t, "pos") else (t.x, t.y),
                                expected_yield=6,
                            )
                        )

        # Feed liabilities from existing animals
        self.feed_liabilities.clear()
        if farm:
            for t in farm.iter_tiles():
                if getattr(t, "is_animal", False) and getattr(t, "animal", None):
                    # Needs feeding today if not yet fed
                    fed_today = getattr(t, "fed_today", False)
                    if not fed_today:
                        self.feed_liabilities.append(
                            DatedFeedLiability(
                                day=self.day,
                                hour_deadline=23,
                                animal_pos=t.pos if hasattr(t, "pos") else (t.x, t.y),
                                species=t.animal,
                                amount=1,
                            )
                        )
                    # And every subsequent day of the season
                    for fut_day in range(self.day + 1, min(30, self.day + 7)):
                        self.feed_liabilities.append(
                            DatedFeedLiability(
                                day=fut_day,
                                hour_deadline=23,
                                animal_pos=t.pos if hasattr(t, "pos") else (t.x, t.y),
                                species=t.animal,
                                amount=1,
                            )
                        )

        # Prune expired liabilities
        self.dated_liabilities = [
            l for l in self.dated_liabilities
            if (l.day > self.day) or (l.day == self.day and l.hour >= self.hour)
        ]
        self.dated_inflows = [
            inf for inf in self.dated_inflows
            if (inf.day > self.day) or (inf.day == self.day and inf.hour >= self.hour)
        ]

    # --- Cash Ledger Management ---

    def reserve_dated_liquidity(self, day: int, hour: int, amount: float, purpose: str, is_hard: bool = True) -> bool:
        """Reserve cash for a future dated obligation.

        Returns True if the required liquidity can be guaranteed without
        compromising existing hard liabilities or dipping below safety reserve at any point.
        """
        temp_candidate = DatedCashLiability(day, hour, amount, purpose, is_hard)
        test_liabilities = self.dated_liabilities + [temp_candidate]

        # Check net available cash at all relevant liability and inflow timepoints
        checkpoints = {(day, hour)} | {(l.day, l.hour) for l in self.dated_liabilities}
        for (cd, ch) in checkpoints:
            cash = self.cash_on_hand - self.safety_reserve
            for inf in self.dated_inflows:
                if (inf.day < cd) or (inf.day == cd and inf.hour <= ch):
                    if inf.confidence in (InflowConfidence.HARD, InflowConfidence.CONSERVATIVE):
                        cash += inf.amount
                    elif not is_hard and inf.confidence == InflowConfidence.SPECULATIVE:
                        cash += inf.amount
            for liab in test_liabilities:
                if (liab.day < cd) or (liab.day == cd and liab.hour <= ch):
                    cash -= liab.amount
            if cash < 0:
                return False

        self.dated_liabilities.append(temp_candidate)
        return True

    def register_inflow(self, day: int, hour: int, amount: float, confidence: InflowConfidence, source: str) -> None:
        """Register an anticipated future cash inflow."""
        self.dated_inflows.append(DatedCashInflow(day, hour, amount, confidence, source))

    def project_available_cash(self, target_day: int, target_hour: int, include_speculative: bool = False) -> float:
        """Calculate conservative net liquidity available at (target_day, target_hour).

        Solvency rule: Hard liabilities CANNOT depend on SPECULATIVE inflows.
        """
        cash = self.cash_on_hand - self.safety_reserve

        # Add inflows maturing before or at (target_day, target_hour)
        for inf in self.dated_inflows:
            if (inf.day < target_day) or (inf.day == target_day and inf.hour <= target_hour):
                if inf.confidence == InflowConfidence.HARD:
                    cash += inf.amount
                elif inf.confidence == InflowConfidence.CONSERVATIVE:
                    cash += inf.amount
                elif include_speculative and inf.confidence == InflowConfidence.SPECULATIVE:
                    cash += inf.amount

        # Subtract all existing liabilities maturing before or at (target_day, target_hour)
        for liab in self.dated_liabilities:
            if (liab.day < target_day) or (liab.day == target_day and liab.hour <= target_hour):
                cash -= liab.amount

        return max(0.0, cash)

    def get_uncommitted_discretionary_cash(self) -> float:
        """Return currently uncommitted liquid capital available for immediate investment."""
        total_committed = sum(l.amount for l in self.dated_liabilities if l.is_hard)
        return max(0.0, self.cash_on_hand - self.safety_reserve - total_committed)

    # --- Feed Ledger Management ---

    def get_accessible_wheat_now(self) -> int:
        """Wheat immediately physically reachable (shed + carried)."""
        return self.shed_wheat + self.worker_carried_wheat

    def project_feed_balance(self, horizon_days: int = 5) -> Dict[str, Any]:
        """Project daily feed surplus/deficit over the next N days.

        Strict causality enforced: in-ground wheat only contributes AFTER its harvest.
        """
        accessible = self.get_accessible_wheat_now()
        daily_projection = {}
        cumulative_balance = accessible

        for offset in range(horizon_days):
            check_day = self.day + offset
            if check_day >= 30:
                break

            # Inflow on check_day from mature harvests
            harvest_inflow = sum(
                h.expected_yield for h in self.in_ground_wheat
                if h.day == check_day
            )

            # Demand on check_day
            feed_demand = sum(
                1 for liab in self.feed_liabilities
                if liab.day == check_day
            )

            cumulative_balance += harvest_inflow - feed_demand
            daily_projection[check_day] = {
                "opening_balance": cumulative_balance + feed_demand - harvest_inflow,
                "harvest_inflow": harvest_inflow,
                "feed_demand": feed_demand,
                "closing_balance": cumulative_balance,
                "is_solvent": cumulative_balance >= 0,
            }

        return {
            "current_accessible": accessible,
            "daily": daily_projection,
            "min_projected_balance": min((d["closing_balance"] for d in daily_projection.values()), default=accessible),
            "is_feed_safe": all(d["is_solvent"] for d in daily_projection.values()),
        }

    # --- Market Order Capacity Management ---

    def can_reserve_market_slots(self, day: int, hour: int, slots_needed: int) -> bool:
        """Check if market turn has sufficient unused order slots (max 10)."""
        existing = sum(
            alloc.slots_consumed
            for alloc in self.turn_order_allocations.get((day, hour), [])
        )
        return (existing + slots_needed) <= 10

    def allocate_market_slots(self, day: int, hour: int, command_type: str, slots_consumed: int, details: Optional[Dict[str, Any]] = None) -> bool:
        """Allocate order slots on a specific market turn."""
        if not self.can_reserve_market_slots(day, hour, slots_consumed):
            return False

        key = (day, hour)
        if key not in self.turn_order_allocations:
            self.turn_order_allocations[key] = []
        self.turn_order_allocations[key].append(
            MarketSlotAllocation(command_type, slots_consumed, details or {})
        )
        return True

    def get_market_slots_remaining(self, day: int, hour: int) -> int:
        """Return free market order slots for (day, hour)."""
        existing = sum(
            alloc.slots_consumed
            for alloc in self.turn_order_allocations.get((day, hour), [])
        )
        return max(0, 10 - existing)

    # --- Storage Ledger Management ---

    def project_storage_headroom(self) -> int:
        """Return conservative available shed space accounting for carried goods."""
        shed_free = max(0, self.shed_capacity - self.current_shed_occupancy)
        # Worker carried units will deposit at shed or midnight
        net_headroom = shed_free - self.current_worker_carried_units
        return max(0, net_headroom)

    def snapshot(self) -> Dict[str, Any]:
        """Return immutable deep-copy summary for telemetry."""
        return {
            "day": self.day,
            "hour": self.hour,
            "cash_on_hand": self.cash_on_hand,
            "safety_reserve": self.safety_reserve,
            "discretionary_cash": self.get_uncommitted_discretionary_cash(),
            "total_hard_liabilities": sum(l.amount for l in self.dated_liabilities if l.is_hard),
            "accessible_wheat": self.get_accessible_wheat_now(),
            "shed_wheat": self.shed_wheat,
            "worker_wheat": self.worker_carried_wheat,
            "shed_occupancy": self.current_shed_occupancy,
            "feed_safe": self.project_feed_balance(horizon_days=3)["is_feed_safe"],
        }
