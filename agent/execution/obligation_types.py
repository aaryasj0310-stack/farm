"""Typed definitions for Service Obligations, Workforce Capacity, and Lifecycle Reservations.

Defines stable typed data structures for:
- ServiceObligation & ObligationLifecycle
- ResourceReservation & ReservationState
- CropCohortState & CropCohortLifecycle
- CapacityForecastResult & Bottleneck diagnostics
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class ObligationLifecycle(str, enum.Enum):
    PROPOSED = "PROPOSED"
    RESERVED = "RESERVED"
    READY = "READY"
    ISSUED = "ISSUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ObligationTier(str, enum.Enum):
    HARD = "HARD"                  # Animal survival feeding, imminent crop decay, terminal sale
    STRATEGIC = "STRATEGIC"        # High-value production: CARE, bonus watering, regular harvest
    DISCRETIONARY = "DISCRETIONARY"# Opportunity/slack: weed digging, early tilling, discretionary fertilizing


class CropCohortLifecycle(str, enum.Enum):
    PROPOSED = "PROPOSED"
    RESERVED = "RESERVED"
    PLANTED = "PLANTED"
    SERVICED = "SERVICED"
    HARVESTED = "HARVESTED"
    REALIZED = "REALIZED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReservationState(str, enum.Enum):
    TRIAL = "TRIAL"
    COMMITTED = "COMMITTED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ResourceType(str, enum.Enum):
    LABOR = "LABOR"
    SEED = "SEED"
    WHEAT_FEED = "WHEAT_FEED"
    FERTILIZER = "FERTILIZER"
    STORAGE_SLOT = "STORAGE_SLOT"
    MARKET_SLOT = "MARKET_SLOT"
    LAND_TILE = "LAND_TILE"


@dataclass
class ServiceObligation:
    """Authoritative identity, requirements, and status for a unit service operation."""
    obligation_id: str                          # Globally unique stable operation ID
    entity_id: str                              # Crop coordinate, animal ID, or structure coordinate
    op: str                                     # PLANT, WATER, FEED, CARE, HARVEST, COLLECT_FERTILIZER, FERTILIZE, PLACE, PICKUP, DROP
    target_pos: Tuple[int, int]
    region: str                                 # NW, NE, SW, SHED
    tier: ObligationTier = ObligationTier.STRATEGIC
    parent_chain_id: Optional[str] = None       # e.g. pickup prerequisite chain
    cohort_id: Optional[str] = None             # parent crop cohort if applicable
    required_item: Optional[str] = None         # WHEAT, SEED, FERTILIZER, etc.
    required_item_qty: int = 0
    prerequisites: List[str] = field(default_factory=list)  # obligation_ids that must complete prior to this
    release_step: int = 0                       # Earliest executable step
    deadline_step: int = 718                    # Hard failure/loss boundary step
    latest_feasible_start_step: int = 718       # Latest step worker can begin travel/execution
    expected_duration_steps: int = 1            # Service duration once at target
    expected_travel_steps: int = 0              # Estimated transit time
    economic_value: float = 0.0                 # Expected whole-farm net cash contribution
    assigned_worker_id: Optional[int] = None
    assigned_step: Optional[int] = None
    lifecycle: ObligationLifecycle = ObligationLifecycle.PROPOSED
    progress_counter: int = 0
    completed_step: Optional[int] = None
    terminal_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.lifecycle in (
            ObligationLifecycle.READY,
            ObligationLifecycle.ISSUED,
            ObligationLifecycle.IN_PROGRESS,
            ObligationLifecycle.RESERVED,
        )

    def is_terminal(self) -> bool:
        return self.lifecycle in (
            ObligationLifecycle.COMPLETED,
            ObligationLifecycle.FAILED,
            ObligationLifecycle.EXPIRED,
            ObligationLifecycle.CANCELLED,
        )


@dataclass
class ResourceReservation:
    """Atomic multi-resource reservation for a commitment."""
    reservation_id: str
    parent_cohort_id: str
    resource_type: ResourceType
    quantity: float
    start_step: int
    end_step: int
    state: ReservationState = ReservationState.TRIAL
    conflict_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CapacityForecastResult:
    """Observation-grounded projection of service feasibility across horizons."""
    forecast_id: str
    source_step: int
    day: int
    hour: int
    feasible_tier: str                          # FEASIBLE, CONSTRAINED, INFEASIBLE
    uncertainty_level: str                      # LOW, MEDIUM, HIGH
    by_worker_hour_capability: Dict[int, Dict[int, float]] = field(default_factory=dict)
    by_region_hour_supply: Dict[str, Dict[int, float]] = field(default_factory=dict)
    by_region_hour_demand: Dict[str, Dict[int, float]] = field(default_factory=dict)
    obligation_forecasts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    unserviceable_obligation_ids: List[str] = field(default_factory=list)
    binding_region: Optional[str] = None
    binding_day: Optional[int] = None
    binding_hour: Optional[int] = None
    binding_resource: Optional[str] = None
    assumed_funded_future_hires: int = 0
    assumed_availability_steps: List[int] = field(default_factory=list)
    predicted_vs_observed_delta: Dict[str, float] = field(default_factory=dict)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
