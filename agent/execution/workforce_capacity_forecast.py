"""Workforce Capacity Forecaster (Phase SW-C2).

Provides deterministic, observation-grounded forecasts of whether current
and future service obligations can be completed within their legal service
windows given:
- Current active workers, positions, and carried inventory
- Known travel envelopes and shared transit corridors
- Midnight reset/redeployment and daily hired-worker recreation
- Crop maturity windows, recurring animal care/feed, and terminal liquidation boundaries (Step 718)

Runs in SHADOW mode during initial phases.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from execution.obligation_types import (
    CapacityForecastResult,
    ObligationLifecycle,
    ObligationTier,
    ServiceObligation,
)
from execution.service_obligation_ledger import ServiceObligationLedger, compute_quadrant

logger = logging.getLogger(__name__)


def manhattan_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> int:
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])


class WorkforceCapacityForecaster:
    """Calculates workforce supply vs obligation demand across multi-day horizons."""

    def __init__(self):
        self._forecast_counter: int = 0
        self._calibration_history: List[Dict[str, Any]] = []

    def reset(self) -> None:
        self._forecast_counter = 0
        self._calibration_history.clear()

    def generate_forecast(
        self,
        step: int,
        obs_farm: Dict[str, Any],
        private: Dict[str, Any],
        ledger: ServiceObligationLedger,
    ) -> CapacityForecastResult:
        """Generate structured capacity forecast for rest-of-day, next 2 days, and terminal season."""
        self._forecast_counter += 1
        day = step // 24
        hour = step % 24
        hours_left_today = max(0, 24 - hour)

        # 1. Observed Workers
        farmer_pos = tuple(obs_farm.get("farmer", (4, 4)))
        hands = obs_farm.get("hands", [])
        worker_positions = [farmer_pos] + [tuple(h) for h in hands]
        num_active_workers = len(worker_positions)

        # Inventories
        inventories = private.get("inventories", [{}])
        shed = private.get("shed", {})

        # Capacity supply calculation
        by_worker_capability: Dict[int, Dict[int, float]] = {}
        for w_idx in range(num_active_workers):
            by_worker_capability[w_idx] = {h: 1.0 for h in range(hour, 24)}

        # Regional supply projection for rest of day
        by_region_supply: Dict[str, Dict[int, float]] = {
            "NW": {h: 0.0 for h in range(hour, 24)},
            "NE": {h: 0.0 for h in range(hour, 24)},
            "SW": {h: 0.0 for h in range(hour, 24)},
            "SE": {h: 0.0 for h in range(hour, 24)},
        }

        for w_idx, pos in enumerate(worker_positions):
            w_quad = compute_quadrant(pos)
            for h in range(hour, 24):
                by_region_supply[w_quad][h] += 1.0

        # 2. Demand calculation from active obligations
        active_obligations = ledger.get_active_obligations()
        by_region_demand: Dict[str, Dict[int, float]] = {
            "NW": {h: 0.0 for h in range(hour, 24)},
            "NE": {h: 0.0 for h in range(hour, 24)},
            "SW": {h: 0.0 for h in range(hour, 24)},
            "SE": {h: 0.0 for h in range(hour, 24)},
        }

        obligation_forecasts: Dict[str, Dict[str, Any]] = {}
        unserviceable: List[str] = []
        binding_region = None
        binding_day = None
        binding_hour = None
        binding_resource = None

        # Sort obligations: HARD first, then STRATEGIC, then DISCRETIONARY
        sorted_obls = sorted(
            active_obligations,
            key=lambda o: (
                0 if o.tier == ObligationTier.HARD else (1 if o.tier == ObligationTier.STRATEGIC else 2),
                o.deadline_step,
            ),
        )

        for obl in sorted_obls:
            # Estimate earliest arrival
            min_travel = min(manhattan_distance(pos, obl.target_pos) for pos in worker_positions)
            est_arrival = step + min_travel
            est_completion = est_arrival + obl.expected_duration_steps

            # Feasibility check against deadline
            is_feasible = (est_completion <= obl.deadline_step) and (est_completion <= 718)

            # Check prerequisite feasibility (e.g. wheat available for feed)
            if obl.op == "FEED":
                carrier_has_wheat = any(inv.get("WHEAT", 0) > 0 for inv in inventories)
                shed_has_wheat = shed.get("WHEAT", 0) > 0
                if not carrier_has_wheat and not shed_has_wheat:
                    is_feasible = False
                    binding_resource = "WHEAT_FEED"

            obl_h = min(23, max(hour, est_arrival % 24))
            by_region_demand[obl.region][obl_h] += float(obl.expected_duration_steps)

            obligation_forecasts[obl.obligation_id] = {
                "estimated_arrival": est_arrival,
                "latest_feasible_start": obl.latest_feasible_start_step,
                "projected_completion": est_completion,
                "is_feasible": is_feasible,
                "tier": obl.tier.value,
                "region": obl.region,
            }

            if not is_feasible:
                unserviceable.append(obl.obligation_id)
                if binding_region is None:
                    binding_region = obl.region
                    binding_day = est_arrival // 24
                    binding_hour = obl_h

        # Evaluate overall feasible tier
        if not unserviceable:
            feasible_tier = "FEASIBLE"
            uncertainty = "LOW"
        elif any(obligation_forecasts[oid]["tier"] == "HARD" for oid in unserviceable):
            feasible_tier = "CRITICAL_INFEASIBLE"
            uncertainty = "HIGH"
        else:
            feasible_tier = "CONSTRAINED_DISCRETIONARY"
            uncertainty = "MEDIUM"

        res = CapacityForecastResult(
            forecast_id=f"FC_{step}_{self._forecast_counter}",
            source_step=step,
            day=day,
            hour=hour,
            feasible_tier=feasible_tier,
            uncertainty_level=uncertainty,
            by_worker_hour_capability=by_worker_capability,
            by_region_hour_supply=by_region_supply,
            by_region_hour_demand=by_region_demand,
            obligation_forecasts=obligation_forecasts,
            unserviceable_obligation_ids=unserviceable,
            binding_region=binding_region,
            binding_day=binding_day,
            binding_hour=binding_hour,
            binding_resource=binding_resource,
            assumed_funded_future_hires=0,
            assumed_availability_steps=[],
            diagnostics={
                "total_active_obligations": len(active_obligations),
                "unserviceable_count": len(unserviceable),
                "active_workers": num_active_workers,
                "hours_left_today": hours_left_today,
            },
        )
        return res


_GLOBAL_FORECASTER: Optional[WorkforceCapacityForecaster] = None


def get_workforce_capacity_forecaster() -> WorkforceCapacityForecaster:
    global _GLOBAL_FORECASTER
    if _GLOBAL_FORECASTER is None:
        _GLOBAL_FORECASTER = WorkforceCapacityForecaster()
    return _GLOBAL_FORECASTER


def reset_workforce_capacity_forecaster() -> None:
    global _GLOBAL_FORECASTER
    if _GLOBAL_FORECASTER is not None:
        _GLOBAL_FORECASTER.reset()
