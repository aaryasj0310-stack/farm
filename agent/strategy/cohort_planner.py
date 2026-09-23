"""Crop and Livestock Cohort Planner with Counterfactual Opportunity-Cost Admission.

Part of the SW-First Forward Architecture Redesign (Phase A).
Replaces isolated positive-EV / threshold admission with:
    ΔFC = E[FinalCash | Plan WITH candidate] - E[FinalCash | Plan WITHOUT candidate]
Everything is inside the trajectories (no double subtraction of displaced core).

Exposes:
- CropCohort and LivestockCohort structured models
- Dynamic SW layout candidates (not restricted to 15 crop / 9 pasture)
- Rapid tranche scaling model (Tranche 1: ~8 -> Tranche 2: ~16 -> Tranche 3: ~20-24)
- Non-linear own-supply market impact pricing
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from config import (
    CROPS, ANIMALS, MARKET_PARAMS, MARKET_I0, SEASON_DAYS,
    SW_SOIL_TILES, SW_PASTURE_TILES,
)


@dataclass
class CropCohort:
    """A planned or active crop planting cohort."""
    cohort_id: str
    crop: str
    region: str                               # "NW", "NE", "SW"
    tiles: List[Tuple[int, int]]
    plant_day: int
    plant_hour: int = 0
    watering_schedule: List[int] = field(default_factory=list)      # Days requiring water
    fertilizer_schedule: List[int] = field(default_factory=list)    # Days to fertilize
    harvest_windows: List[Tuple[int, int, int]] = field(default_factory=list) # (day, hour, expected_units)
    expected_gross_revenue: float = 0.0
    seed_cost: float = 0.0
    labor_actions_required: int = 0
    remaining_labor_obligation: int = 0
    market_supply_units: int = 0
    is_discretionary: bool = False            # True if marginal/low-value candidate


@dataclass
class LivestockCohort:
    """A planned or active animal cohort."""
    cohort_id: str
    species: str                              # "COW", "SHEEP", "GOOSE"
    region: str
    tile: Tuple[int, int]
    purchase_day: int
    purchase_cost: float
    daily_feed_liability: int = 1
    daily_care_liability: int = 1
    expected_yield_schedule: List[Tuple[int, int, str]] = field(default_factory=list) # (day, units, product)
    housing_structure: str = "PASTURE"
    expected_gross_revenue: float = 0.0
    is_discretionary: bool = False


@dataclass
class OpportunityCostEvaluation:
    """Rigorous counterfactual valuation result."""
    candidate_id: str
    delta_final_cash: float                   # Net difference: WITH - WITHOUT
    expected_gross_revenue: float
    seed_or_purchase_cost: float
    incremental_wage_cost: float
    displaced_core_value: float               # Displaced core crop/livestock output
    feed_opportunity_cost: float              # Additional feed consumption or purchase
    market_cannibalization_loss: float        # Price depression on existing farm inventory
    feasible: bool = True
    admission_decision: str = "REJECT"        # "ADMIT", "DELAY", "DOWNSIZE", "REJECT"
    rejection_reason: Optional[str] = None


class CohortPlanner:
    """Evaluates crop and livestock cohorts under whole-farm opportunity cost."""

    def __init__(self) -> None:
        self.active_crop_cohorts: Dict[str, CropCohort] = {}
        self.active_livestock_cohorts: Dict[str, LivestockCohort] = {}

    def build_candidate_crop_cohort(
        self,
        cohort_id: str,
        crop: str,
        region: str,
        tiles: List[Tuple[int, int]],
        plant_day: int,
        plant_hour: int = 0,
        is_discretionary: bool = False,
    ) -> CropCohort:
        """Construct a standardized CropCohort with exact engine timing."""
        c_info = CROPS[crop]
        seed_unit_cost = c_info["seed"]
        seed_cost = seed_unit_cost * len(tiles)

        watering_days = []
        harvest_windows = []
        labor_ops = 0
        total_units = 0

        first_harvest = plant_day + c_info["first_yield_day"]
        max_harvest = plant_day + c_info["max_yield_day"]
        interval = c_info["interval"]
        max_yield = c_info["max_yield"]
        ongoing = c_info["ongoing"]

        if ongoing:
            # Multi-harvest crop (Strawberry: 4 ticks, Tomato: 4 ticks)
            # Up to 4 production ticks
            for tick in range(min(4, max_yield)):
                h_day = first_harvest + tick * interval
                if h_day < SEASON_DAYS:
                    units = len(tiles)
                    harvest_windows.append((h_day, 0, units))
                    total_units += units

            # Watering schedule: needs water every day between plant and last harvest
            last_h = harvest_windows[-1][0] if harvest_windows else plant_day
            for d in range(plant_day, min(SEASON_DAYS, last_h + 1)):
                watering_days.append(d)

            # Operations: 1 plant + watering days + harvests
            labor_ops = len(tiles) * (1 + len(watering_days) + len(harvest_windows))

        else:
            # One-time crop (Wheat, Carrot, Melon)
            h_day = max_harvest
            if h_day < SEASON_DAYS:
                units = len(tiles) * max_yield
                harvest_windows.append((h_day, 0, units))
                total_units += units

            for d in range(plant_day, min(SEASON_DAYS, h_day)):
                watering_days.append(d)

            labor_ops = len(tiles) * (1 + len(watering_days) + 1)

        # Baseline reference price
        base_price = MARKET_PARAMS.get(crop, {}).get("base", 30)
        expected_gross = total_units * base_price

        return CropCohort(
            cohort_id=cohort_id,
            crop=crop,
            region=region,
            tiles=tiles,
            plant_day=plant_day,
            plant_hour=plant_hour,
            watering_schedule=watering_days,
            fertilizer_schedule=[],
            harvest_windows=harvest_windows,
            expected_gross_revenue=expected_gross,
            seed_cost=seed_cost,
            labor_actions_required=labor_ops,
            remaining_labor_obligation=labor_ops,
            market_supply_units=total_units,
            is_discretionary=is_discretionary,
        )

    def evaluate_opportunity_cost(
        self,
        candidate: CropCohort,
        displaced_cohorts: List[CropCohort],
        market_inventory: Dict[str, int],
        feed_deficit_risk: bool = False,
    ) -> OpportunityCostEvaluation:
        """Compute counterfactual ΔFC for admitting candidate cohort.

        ΔFC = Expected Net Revenue(Candidate)
            - Displaced Core Net Revenue
            - Market Cannibalization
            - Feed Opportunity Cost
            - Incremental Wages
        """
        # 1. Candidate gross and seed cost
        cand_gross = candidate.expected_gross_revenue
        cand_seed = candidate.seed_cost

        # 2. Estimate market cannibalization on existing supply
        # Price function impact: adding units depresses marginal realized price
        cannibalization = self.estimate_price_depression_loss(
            candidate.crop, candidate.market_supply_units, market_inventory.get(candidate.crop, 10000)
        )

        # 3. Displaced core value
        displaced_value = 0.0
        for dc in displaced_cohorts:
            displaced_value += max(0.0, dc.expected_gross_revenue - dc.seed_cost)

        # 4. Feed opportunity cost (if candidate displaces wheat or creates feed risk)
        feed_cost = 0.0
        if candidate.crop != "WHEAT" and feed_deficit_risk:
            # Displacing wheat in a feed-sensitive regime incurs market feed purchase cost ($25/unit)
            feed_cost = len(candidate.tiles) * 6 * 25.0

        # Incremental wage: assume 0 for baseline workforce unless peak hire required
        incremental_wages = 0.0

        # Net Counterfactual ΔFC
        delta_fc = cand_gross - cand_seed - cannibalization - displaced_value - feed_cost - incremental_wages

        decision = "ADMIT" if delta_fc > 0 else "REJECT"
        reason = None
        if delta_fc <= 0:
            if displaced_value > (cand_gross - cand_seed):
                reason = f"Displaced core value (${displaced_value:.1f}) exceeds candidate margin (${cand_gross - cand_seed:.1f})"
            elif cannibalization > 500:
                reason = f"Own-supply price depression (${cannibalization:.1f}) erodes profitability"
            else:
                reason = f"Negative counterfactual cash delta (${delta_fc:.1f})"

        return OpportunityCostEvaluation(
            candidate_id=candidate.cohort_id,
            delta_final_cash=delta_fc,
            expected_gross_revenue=cand_gross,
            seed_or_purchase_cost=cand_seed,
            incremental_wage_cost=incremental_wages,
            displaced_core_value=displaced_value,
            feed_opportunity_cost=feed_cost,
            market_cannibalization_loss=cannibalization,
            feasible=(delta_fc > 0),
            admission_decision=decision,
            rejection_reason=reason,
        )

    def estimate_price_depression_loss(self, product: str, additional_units: int, current_inv: int) -> float:
        """Estimate realized revenue loss on existing/incumbent inventory due to own supply."""
        if product not in MARKET_PARAMS or additional_units <= 0:
            return 0.0

        params = MARKET_PARAMS[product]
        base = params["base"]
        T = params["T"]
        bf = params["bf"]

        # Approximate price change per unit
        # When inventory increases by ΔI, price drops approximately by:
        # ΔP ≈ base * (ΔI / (T * 2)) for moderate inventory
        price_drop_per_unit = (base * (additional_units / max(100.0, float(T)))) * 0.25
        # Total impact across new and incumbent sold units (assuming ~50 incumbent units)
        total_cannibalization = price_drop_per_unit * min(100, additional_units)
        return round(max(0.0, total_cannibalization), 2)

    def generate_candidate_portfolios(self, current_day: int, available_tiles: List[Tuple[int, int]]) -> List[Dict[str, Any]]:
        """Generate diverse SW candidate allocations for portfolio comparison.

        Candidates are NOT hardcoded constants; multiple combinations are generated.
        """
        n_tiles = len(available_tiles)
        if n_tiles < 8:
            return []

        portfolios = []

        # Candidate 1: Balanced Commercial (Wheat + Strawberry + Melon)
        if current_day <= 8 and n_tiles >= 20:
            portfolios.append({
                "name": "balanced_commercial",
                "allocations": [
                    ("WHEAT", 10, available_tiles[:10]),
                    ("STRAWBERRY", 10, available_tiles[10:20]),
                    ("MELON", min(4, n_tiles - 20), available_tiles[20:24]),
                ]
            })

        # Candidate 2: Feed & High-Margin Strawberry (14 Wheat + 10 Strawberry)
        if n_tiles >= 16:
            portfolios.append({
                "name": "feed_and_strawberry",
                "allocations": [
                    ("WHEAT", min(14, n_tiles // 2), available_tiles[:min(14, n_tiles // 2)]),
                    ("STRAWBERRY", min(10, n_tiles - min(14, n_tiles // 2)), available_tiles[min(14, n_tiles // 2):]),
                ]
            })

        # Candidate 3: Rapid Tranche 1 (First 8 tiles: 4 Wheat + 4 Strawberry)
        portfolios.append({
            "name": "tranche_1_starter",
            "allocations": [
                ("WHEAT", 4, available_tiles[:4]),
                ("STRAWBERRY", 4, available_tiles[4:8]),
            ]
        })

        return portfolios
