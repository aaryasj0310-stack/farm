"""Workforce Capacity Forecaster (Phase SW-C2).

Provides deterministic, observation-grounded forecasts of whether current
and future service obligations can be completed within their legal service
windows given:
- Current active workers, positions, and carried inventory
- Time-dependent worker availability queues and competing worker assignments
- Service-chain prerequisites (shed pickup before feeding/planting)
- Known travel envelopes and shared transit corridors
- Midnight reset/redeployment and daily hired-worker recreation (House (4,4) at H06)
- Crop maturity windows, recurring animal care/feed, and terminal liquidation boundaries (Step 718)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from execution.obligation_types import (
    CapacityForecastResult,
    ObligationLifecycle,
    ObligationTier,
    ServiceObligation,
)
from execution.service_obligation_ledger import ServiceObligationLedger, compute_quadrant

logger = logging.getLogger(__name__)

SHED_ACCESS_TILES: List[Tuple[int, int]] = [(4, 4), (4, 5), (5, 4)]
PORT_SW: Tuple[int, int] = (4, 5)


def manhattan_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> int:
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])


def nearest_shed_access(pos: Tuple[int, int]) -> Tuple[int, int]:
    return min(SHED_ACCESS_TILES, key=lambda p: manhattan_distance(pos, p))


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
        """Generate structured capacity forecast for rest-of-day, next 2 days, and terminal season.
        
        Explicitly tracks time-dependent worker availability, competing worker assignments,
        and prerequisite chains (pickup -> travel -> action).
        """
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
        shed = dict(private.get("shed", {}))

        # Time-dependent availability queues for active workers today
        w_available_step: List[int] = [step] * num_active_workers
        w_current_pos: List[Tuple[int, int]] = list(worker_positions)
        w_inventories: List[Dict[str, int]] = [dict(inv) for inv in (inventories or [{}])]
        while len(w_inventories) < num_active_workers:
            w_inventories.append({})

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

        # Sort obligations: HARD first, then STRATEGIC, then DISCRETIONARY, then deadline
        sorted_obls = sorted(
            active_obligations,
            key=lambda o: (
                0 if o.tier == ObligationTier.HARD else (1 if o.tier == ObligationTier.STRATEGIC else 2),
                o.deadline_step,
            ),
        )

        prereq_completion_step: Dict[str, int] = {}

        for obl in sorted_obls:
            # Service-chain prerequisite check: cannot start until release_step and prerequisites complete
            earliest_start = max(step, getattr(obl, "release_step", step))
            if obl.prerequisites:
                earliest_start = max(
                    earliest_start,
                    max([prereq_completion_step.get(p, step) for p in obl.prerequisites], default=step),
                )

            # Evaluate each worker under competing availability queues and service-chain requirements
            best_w_idx: Optional[int] = None
            best_completion: int = 999999
            best_arrival: int = 999999
            missing_resource: bool = False

            for w_idx in range(num_active_workers):
                w_start_step = max(w_available_step[w_idx], earliest_start)
                w_pos = w_current_pos[w_idx]

                # Check item dependency (e.g. FEED requires WHEAT, PLANT requires SEED)
                if obl.op == "FEED":
                    if w_inventories[w_idx].get("WHEAT", 0) > 0:
                        transit = manhattan_distance(w_pos, obl.target_pos)
                    elif shed.get("WHEAT", 0) > 0:
                        s_pt = nearest_shed_access(w_pos)
                        # Transit to shed + 1 step pickup + transit from shed to target
                        transit = manhattan_distance(w_pos, s_pt) + 1 + manhattan_distance(s_pt, obl.target_pos)
                    else:
                        missing_resource = True
                        continue
                elif obl.op == "PLANT" and obl.required_item:
                    item_name = obl.required_item
                    if w_inventories[w_idx].get(item_name, 0) > 0:
                        transit = manhattan_distance(w_pos, obl.target_pos)
                    elif shed.get(item_name, 0) > 0:
                        s_pt = nearest_shed_access(w_pos)
                        transit = manhattan_distance(w_pos, s_pt) + 1 + manhattan_distance(s_pt, obl.target_pos)
                    else:
                        missing_resource = True
                        continue
                else:
                    transit = manhattan_distance(w_pos, obl.target_pos)

                arrival = w_start_step + transit
                completion = arrival + obl.expected_duration_steps

                if completion < best_completion:
                    best_completion = completion
                    best_arrival = arrival
                    best_w_idx = w_idx

            if best_w_idx is None:
                # Missing resource or no worker available
                is_feasible = False
                binding_resource = obl.required_item or ("WHEAT_FEED" if obl.op == "FEED" else "WORKER")
                est_arrival = step + 999
                est_completion = step + 999
            else:
                is_feasible = (best_completion <= obl.deadline_step) and (best_completion <= 718)
                est_arrival = best_arrival
                est_completion = best_completion

                if is_feasible:
                    # Update winning worker's queue and location (competing allocation)
                    w_available_step[best_w_idx] = best_completion
                    w_current_pos[best_w_idx] = obl.target_pos
                    # Decrement simulated resource inventory
                    if obl.op == "FEED":
                        if w_inventories[best_w_idx].get("WHEAT", 0) > 0:
                            w_inventories[best_w_idx]["WHEAT"] -= 1
                        elif shed.get("WHEAT", 0) > 0:
                            shed["WHEAT"] -= 1
                    elif obl.op == "PLANT" and obl.required_item:
                        item_name = obl.required_item
                        if w_inventories[best_w_idx].get(item_name, 0) > 0:
                            w_inventories[best_w_idx][item_name] -= 1
                        elif shed.get(item_name, 0) > 0:
                            shed[item_name] -= 1

                prereq_completion_step[obl.obligation_id] = best_completion

            obl_h = min(23, max(hour, est_arrival % 24))
            by_region_demand[obl.region][obl_h] += float(obl.expected_duration_steps)

            obligation_forecasts[obl.obligation_id] = {
                "estimated_arrival": est_arrival,
                "latest_feasible_start": obl.latest_feasible_start_step,
                "projected_completion": est_completion,
                "is_feasible": is_feasible,
                "tier": obl.tier.value,
                "region": obl.region,
                "assigned_worker_projection": best_w_idx,
            }

            if not is_feasible:
                unserviceable.append(obl.obligation_id)
                if binding_region is None:
                    binding_region = obl.region
                    binding_day = est_arrival // 24
                    binding_hour = obl_h

        # Multi-day conservative future outlook (Day d+1 and d+2)
        future_days_forecast: Dict[int, Dict[str, Any]] = {}
        for future_d in range(day + 1, min(30, day + 3)):
            # Morning hiring: farmer starts at H00 (24h), hands recreate at H06 (18h each)
            future_supply_hours = 24.0 + (18.0 * max(0, num_active_workers - 1))
            # Base recurring maintenance: feed/care for livestock + basic watering
            future_days_forecast[future_d] = {
                "estimated_supply_hours": future_supply_hours,
                "hired_workers_expected": max(0, num_active_workers - 1),
                "safe_load_headroom": future_supply_hours * 0.85,
            }

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
            assumed_funded_future_hires=max(0, num_active_workers - 1),
            assumed_availability_steps=w_available_step,
            diagnostics={
                "total_active_obligations": len(active_obligations),
                "unserviceable_count": len(unserviceable),
                "active_workers": num_active_workers,
                "hours_left_today": hours_left_today,
                "worker_final_availability_steps": w_available_step,
                "future_days_forecast": future_days_forecast,
            },
        )
        return res

    def evaluate_candidate_schedule(
        self,
        candidate_obligations: List[ServiceObligation],
        current_step: int,
        obs_farm: Dict[str, Any],
        private: Dict[str, Any],
        ledger: ServiceObligationLedger,
        max_load_threshold: float = 0.85,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Evaluate whether candidate obligations can be integrated into existing workforce commitments.
        
        Replaces crude aggregate heuristic checks with time-dependent multi-day capacity validation.
        """
        day = current_step // 24
        hour = current_step % 24
        hands = obs_farm.get("hands", [])
        num_workers = 1 + len(hands)

        # 1. Group candidate obligations by target day
        candidate_by_day: Dict[int, List[ServiceObligation]] = {}
        for obl in candidate_obligations:
            o_day = obl.release_step // 24
            candidate_by_day.setdefault(o_day, []).append(obl)

        # 2. Check each active day in candidate cycle
        for o_day, obls in sorted(candidate_by_day.items()):
            if o_day < day or o_day >= 30:
                continue

            # Calculate daily supply worker hours
            if o_day == day:
                daily_supply = float(max(1, num_workers) * max(0, 24 - hour))
            else:
                # Farmer 24h + hands 18h
                daily_supply = 24.0 + (18.0 * max(0, num_workers - 1))

            max_allowed = daily_supply * max_load_threshold

            # Count existing active chores in ledger for this day
            existing_obls = [
                o for o in ledger.get_active_obligations()
                if (o.release_step // 24) == o_day
            ]
            existing_hours = sum(o.expected_duration_steps for o in existing_obls)
            candidate_hours = sum(o.expected_duration_steps for o in obls)

            # Transit overhead: conservative ~2 turns per candidate operation across quadrant
            transit_overhead = len(obls) * 2.0
            total_projected_demand = existing_hours + candidate_hours + transit_overhead

            if total_projected_demand > max_allowed:
                reason = (
                    f"Labor overload on Day {o_day}: projected demand {total_projected_demand:.1f}h "
                    f"(existing {existing_hours:.1f}h + candidate {candidate_hours:.1f}h + transit {transit_overhead:.1f}h) "
                    f"> allowable {max_allowed:.1f}h ({max_load_threshold*100:.0f}% of {daily_supply:.1f}h supply)"
                )
                return False, reason, {
                    "binding_day": o_day,
                    "projected_demand": total_projected_demand,
                    "max_allowed": max_allowed,
                    "daily_supply": daily_supply,
                }

        return True, "OK", {"status": "FEASIBLE"}


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
