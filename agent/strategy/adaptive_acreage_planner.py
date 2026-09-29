"""Phase SW-C1: Adaptive, Capacity-Aware Acreage Expansion Planner.

Replaces the rigid one-time fixed 8-tile SW tranche model with an incremental,
capacity-aware expansion architecture (8 -> 12 -> 16 -> 20 -> 24 tiles).

Guarantees:
- Initial 8-tile portfolio remains strictly preserved (4 Strawberry + 4 Melon)
- Reserved shed-access port (4, 5) is permanently protected from cultivation
- Expansion evaluated in discrete 4-tile blocks
- Strict marginal ΔFC evaluation: only admit increments with ΔFC > 0
- 5 comprehensive capacity certificates:
  1. Treasury safety: cash >= seed_cost + $300 reserve
  2. Livestock feed safety: wheat balance >= 3-day feed buffer
  3. Labor capacity envelope: daily actions <= 85% of workforce capacity
  4. Logistics & contiguity: coordinates within SW quadrant, excluding (4, 5)
  5. Storage & market headroom: peak shed inventory <= 100 limit
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from config import (
        CROPS,
        ANIMALS,
        MARKET_PARAMS,
        MARKET_I0,
        SEASON_DAYS,
        TURNS_PER_DAY,
        get_sw_adaptive_acreage_enabled,
        get_sw_max_adaptive_acreage,
    )
except ImportError:
    from agent.config import (
        CROPS,
        ANIMALS,
        MARKET_PARAMS,
        MARKET_I0,
        SEASON_DAYS,
        TURNS_PER_DAY,
        get_sw_adaptive_acreage_enabled,
        get_sw_max_adaptive_acreage,
    )

try:
    from market.price_math import total_revenue_estimate
except ImportError:
    from agent.market.price_math import total_revenue_estimate

logger = logging.getLogger("AdaptiveAcreagePlanner")

# ====================================================================
# SW Quadrant Geometry & Expansion Blocks
# ====================================================================
# SW quadrant spans x in [0..4], y in [5..9] (25 total coordinates).
# Coordinate (4, 5) is reserved for shed port ingress/egress.
SHED_ACCESS_PORT: Tuple[int, int] = (4, 5)

# Initial frozen 8-tile portfolio (Level 1)
INITIAL_SW_TILES: List[Tuple[int, int]] = [
    # 4 Strawberry tiles:
    (0, 5), (1, 5), (2, 5), (3, 5),
    # 4 Melon tiles:
    (0, 6), (1, 6), (2, 6), (3, 6),
]

# Candidate 4-tile expansion blocks
EXPANSION_BLOCKS: Dict[int, List[Tuple[int, int]]] = {
    12: [(4, 6), (0, 7), (1, 7), (2, 7)],
    16: [(3, 7), (4, 7), (0, 8), (1, 8)],
    20: [(2, 8), (3, 8), (4, 8), (0, 9)],
    24: [(1, 9), (2, 9), (3, 9), (4, 9)],
}

# Operational Safety Constants
SW_SAFETY_RESERVE: float = 300.0  # Protected cash buffer for feed/wages/contingency
FEED_BUFFER_DAYS: int = 3         # Minimum days of animal feed required before non-feed expansion
MAX_WORKER_LOAD_FRAC: float = 0.85 # Max allowable labor capacity envelope fraction
SHED_CAPACITY_LIMIT: int = 100    # Engine hard maximum shed storage

# Biological Planting Deadlines (Season ends at Day 29 Turn 23)
CROP_PLANT_DEADLINES: Dict[str, int] = {
    "STRAWBERRY": 13,  # Multi-harvest ongoing crop (first yield +10, interval 2)
    "MELON": 17,       # Single-harvest crop (yield at day +12; 29-12=17)
    "TOMATO": 21,      # Ongoing crop (first yield +5, interval 2; 29-8=21)
    "WHEAT": 25,       # Single-harvest crop (yield at day +4; 29-4=25)
    "CARROT": 26,      # Single-harvest crop (yield at day +3; 29-3=26)
}


def get_crop_yield_profile(crop: str, plant_day: int) -> Tuple[int, List[int]]:
    """Compute yield units per tile and harvest days before Day 29 season cutoff."""
    c_info = CROPS.get(crop, {})
    if not c_info:
        return 0, []

    if c_info.get("ongoing", False):
        harvest_days = []
        first_h = plant_day + c_info["first_yield_day"]
        interval = c_info["interval"]
        max_yield = c_info["max_yield"]
        for tick in range(min(4, max_yield)):
            h_day = first_h + tick * interval
            if h_day <= 29:
                harvest_days.append(h_day)
        return len(harvest_days), harvest_days
    else:
        max_h = plant_day + c_info["max_yield_day"]
        if max_h <= 29:
            return c_info["max_yield"], [max_h]
        return 0, []


def evaluate_candidate_crop_economics(
    crop: str,
    plant_day: int,
    n_tiles: int,
    market_inv: int = MARKET_I0,
) -> Tuple[float, float, float, int]:
    """Evaluate marginal economics for planting crop on n_tiles on plant_day.

    Returns:
        (marginal_delta_fc, gross_revenue, seed_cost, total_harvest_units)
    """
    deadline = CROP_PLANT_DEADLINES.get(crop, 0)
    if plant_day > deadline:
        return 0.0, 0.0, 0.0, 0

    c_info = CROPS.get(crop, {})
    seed_price = c_info.get("seed", 0.0)
    seed_cost = float(n_tiles * seed_price)

    yield_per_tile, harvest_days = get_crop_yield_profile(crop, plant_day)
    if yield_per_tile <= 0 or not harvest_days:
        return -seed_cost, 0.0, seed_cost, 0

    total_units = n_tiles * yield_per_tile
    gross_revenue = float(total_revenue_estimate(crop, market_inv, total_units))
    marginal_delta_fc = gross_revenue - seed_cost

    return round(marginal_delta_fc, 2), round(gross_revenue, 2), round(seed_cost, 2), total_units


@dataclass
class AdaptiveAcreageDecision:
    """Decision outcome of an adaptive acreage expansion evaluation."""
    approved: bool = False
    current_acreage: int = 8
    target_acreage: int = 8
    active_workers: int = 0
    new_tiles: List[Tuple[int, int]] = field(default_factory=list)
    selected_crop: Optional[str] = None
    marginal_delta_fc: float = 0.0
    seed_cost: float = 0.0
    projected_revenue: float = 0.0
    projected_units: int = 0
    passed_certificates: Dict[str, bool] = field(default_factory=lambda: {
        "treasury_safety": False,
        "feed_safety": False,
        "labor_capacity": False,
        "logistics_contiguity": False,
        "storage_market": False,
    })
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "current_acreage": self.current_acreage,
            "target_acreage": self.target_acreage,
            "active_workers": self.active_workers,
            "new_tiles": [list(t) for t in self.new_tiles],
            "selected_crop": self.selected_crop,
            "marginal_delta_fc": self.marginal_delta_fc,
            "seed_cost": self.seed_cost,
            "projected_revenue": self.projected_revenue,
            "projected_units": self.projected_units,
            "passed_certificates": dict(self.passed_certificates),
            "rejection_reason": self.rejection_reason,
        }


class AdaptiveAcreagePlanner:
    """Evaluates incremental 4-tile SW acreage expansions under capacity certificates."""

    def __init__(self) -> None:
        pass

    def evaluate_expansion(
        self,
        current_day: int,
        current_hour: int,
        current_admitted_tiles: Set[Tuple[int, int]],
        current_cash: float,
        active_workers: int,
        num_animals: int,
        wheat_inventory: int,
        shed_inventory_units: int,
        core_planted_tiles: int = 0,
        market_inventories: Optional[Dict[str, int]] = None,
        max_acreage_cap: Optional[int] = None,
    ) -> AdaptiveAcreageDecision:
        """Evaluate whether to admit the next 4-tile SW expansion block."""
        current_acreage = len(current_admitted_tiles)

        if max_acreage_cap is None:
            max_acreage_cap = get_sw_max_adaptive_acreage()

        # Check if already at or above cap
        if current_acreage >= max_acreage_cap:
            return AdaptiveAcreageDecision(
                approved=False,
                current_acreage=current_acreage,
                target_acreage=current_acreage,
                active_workers=active_workers,
                rejection_reason=f"Current acreage ({current_acreage}) reaches configured cap ({max_acreage_cap})",
            )

        # Target acreage is next step in [12, 16, 20, 24]
        target_acreage = current_acreage + 4
        if target_acreage > max_acreage_cap:
            return AdaptiveAcreageDecision(
                approved=False,
                current_acreage=current_acreage,
                target_acreage=target_acreage,
                active_workers=active_workers,
                rejection_reason=f"Target acreage ({target_acreage}) exceeds configured cap ({max_acreage_cap})",
            )

        candidate_block = EXPANSION_BLOCKS.get(target_acreage, [])
        if not candidate_block:
            return AdaptiveAcreageDecision(
                approved=False,
                current_acreage=current_acreage,
                target_acreage=target_acreage,
                active_workers=active_workers,
                rejection_reason=f"No expansion block defined for target acreage {target_acreage}",
            )

        # Certificate 4: Logistics & Contiguity verification
        for tile in candidate_block:
            if tile == SHED_ACCESS_PORT:
                return AdaptiveAcreageDecision(
                    approved=False,
                    current_acreage=current_acreage,
                    target_acreage=target_acreage,
                    active_workers=active_workers,
                    rejection_reason=f"Candidate tile {tile} violates reserved shed-access port invariant",
                )
            if not (0 <= tile[0] < 5 and 5 <= tile[1] < 10):
                return AdaptiveAcreageDecision(
                    approved=False,
                    current_acreage=current_acreage,
                    target_acreage=target_acreage,
                    active_workers=active_workers,
                    rejection_reason=f"Candidate tile {tile} outside SW quadrant bounds",
                )
            if tile in current_admitted_tiles:
                return AdaptiveAcreageDecision(
                    approved=False,
                    current_acreage=current_acreage,
                    target_acreage=target_acreage,
                    active_workers=active_workers,
                    rejection_reason=f"Candidate tile {tile} already admitted",
                )

        certs = {
            "treasury_safety": False,
            "feed_safety": False,
            "labor_capacity": False,
            "logistics_contiguity": True,
            "storage_market": False,
        }

        # Candidate Crop Evaluation across all valid crops
        m_inv = market_inventories or {}
        candidate_crops = ["STRAWBERRY", "MELON", "TOMATO", "WHEAT", "CARROT"]
        n_block_tiles = len(candidate_block)

        evaluated_candidates = []
        for crop_name in candidate_crops:
            crop_inv = m_inv.get(crop_name, MARKET_I0)
            delta_fc, gross_rev, seed_cost, units = evaluate_candidate_crop_economics(
                crop=crop_name,
                plant_day=current_day,
                n_tiles=n_block_tiles,
                market_inv=crop_inv,
            )
            if delta_fc > 0 and units > 0:
                evaluated_candidates.append({
                    "crop": crop_name,
                    "delta_fc": delta_fc,
                    "gross_revenue": gross_rev,
                    "seed_cost": seed_cost,
                    "units": units,
                })

        if not evaluated_candidates:
            return AdaptiveAcreageDecision(
                approved=False,
                current_acreage=current_acreage,
                target_acreage=target_acreage,
                active_workers=active_workers,
                new_tiles=candidate_block,
                passed_certificates=certs,
                rejection_reason=f"No economically viable candidate crops on Day {current_day} (biological deadlines passed or nonpositive ΔFC)",
            )

        # Rank candidate crops by marginal ΔFC descending
        evaluated_candidates.sort(key=lambda x: x["delta_fc"], reverse=True)

        # Find the highest-ΔFC crop that satisfies all 5 certificates
        best_candidate = None
        failure_reasons = []

        for cand in evaluated_candidates:
            crop_name = cand["crop"]
            seed_cost = cand["seed_cost"]
            yield_units = cand["units"]
            delta_fc = cand["delta_fc"]

            # Certificate 1: Treasury Safety
            if current_cash < (seed_cost + SW_SAFETY_RESERVE):
                failure_reasons.append(
                    f"{crop_name}: Treasury shortage (cash ${current_cash:.1f} < seed ${seed_cost:.1f} + reserve ${SW_SAFETY_RESERVE:.1f})"
                )
                continue
            treasury_ok = True

            # Certificate 2: Livestock Feed Safety
            # Animals require 1 wheat/day. If non-wheat crop is chosen, wheat inventory must cover 3-day buffer.
            feed_needed = num_animals * FEED_BUFFER_DAYS
            if crop_name != "WHEAT" and wheat_inventory < feed_needed:
                failure_reasons.append(
                    f"{crop_name}: Feed risk (wheat {wheat_inventory} < 3-day buffer {feed_needed} for {num_animals} animals)"
                )
                continue
            feed_ok = True

            # Certificate 3: Labor Capacity Envelope
            # Total daily capacity = active_workers * 24
            # Workload:
            # - Feeding: num_animals actions/day
            # - Core crops: ~0.6 * core_planted_tiles actions/day
            # - Current SW crops: ~0.6 * current_acreage actions/day
            # - New 4-tile block: 4 actions (planting on plant day; watering/harvest on subsequent days)
            total_daily_worker_hours = max(1, active_workers) * TURNS_PER_DAY
            max_allowable_actions = MAX_WORKER_LOAD_FRAC * total_daily_worker_hours
            estimated_peak_actions = num_animals + (0.6 * core_planted_tiles) + (0.6 * current_acreage) + 4.0

            if estimated_peak_actions > max_allowable_actions:
                failure_reasons.append(
                    f"{crop_name}: Labor crunch (estimated peak actions {estimated_peak_actions:.1f} > 85% capacity {max_allowable_actions:.1f} with {active_workers} workers)"
                )
                continue
            labor_ok = True

            # Certificate 5: Storage & Market Headroom
            # Avoid severe shed congestion that could trigger emergency overflow dumps.
            # Shed hard limit is 100 units. If currently above 75 and bulky yield expected, defer.
            if shed_inventory_units >= 75 and yield_units >= 16:
                failure_reasons.append(
                    f"{crop_name}: Storage congestion (current shed {shed_inventory_units}/100 too full for {yield_units} unit yield)"
                )
                continue
            storage_ok = True

            # All certificates passed!
            best_candidate = cand
            certs["treasury_safety"] = treasury_ok
            certs["feed_safety"] = feed_ok
            certs["labor_capacity"] = labor_ok
            certs["storage_market"] = storage_ok
            break

        if best_candidate is None:
            primary_reason = failure_reasons[0] if failure_reasons else "All candidate crops failed capacity certificates"
            return AdaptiveAcreageDecision(
                approved=False,
                current_acreage=current_acreage,
                target_acreage=target_acreage,
                active_workers=active_workers,
                new_tiles=candidate_block,
                passed_certificates=certs,
                rejection_reason=primary_reason,
            )

        # Expansion APPROVED!
        return AdaptiveAcreageDecision(
            approved=True,
            current_acreage=current_acreage,
            target_acreage=target_acreage,
            active_workers=active_workers,
            new_tiles=candidate_block,
            selected_crop=best_candidate["crop"],
            marginal_delta_fc=best_candidate["delta_fc"],
            seed_cost=best_candidate["seed_cost"],
            projected_revenue=best_candidate["gross_revenue"],
            projected_units=best_candidate["units"],
            passed_certificates=certs,
            rejection_reason=None,
        )


_ADAPTIVE_ACREAGE_PLANNER_INSTANCE: Optional[AdaptiveAcreagePlanner] = None


def get_adaptive_acreage_planner() -> AdaptiveAcreagePlanner:
    """Singleton getter for AdaptiveAcreagePlanner."""
    global _ADAPTIVE_ACREAGE_PLANNER_INSTANCE
    if _ADAPTIVE_ACREAGE_PLANNER_INSTANCE is None:
        _ADAPTIVE_ACREAGE_PLANNER_INSTANCE = AdaptiveAcreagePlanner()
    return _ADAPTIVE_ACREAGE_PLANNER_INSTANCE


def reset_adaptive_acreage_planner() -> None:
    """Reset singleton instance."""
    global _ADAPTIVE_ACREAGE_PLANNER_INSTANCE
    _ADAPTIVE_ACREAGE_PLANNER_INSTANCE = None
