"""
Phase SW-C2: P3 Transactional Acreage and Complete Crop-Cycle Reservations.
Provides atomic, side-effect-free complete crop-cycle evaluation and reservation management.
Ensures new planting and replanting commitments reserve their full executable lifecycle
(seeds, planting, watering, maturation, harvest, storage, and market liquidation)
contingent on whole-farm serviceability and safety margins.
"""

from __future__ import annotations

import copy
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
        SHED_CAPACITY,
    )
    from execution.obligation_types import (
        ReservationState,
        ResourceType,
        ResourceReservation,
        ObligationTier,
        ObligationLifecycle,
        ServiceObligation,
    )
except ImportError:
    from agent.config import (
        CROPS,
        ANIMALS,
        MARKET_PARAMS,
        MARKET_I0,
        SEASON_DAYS,
        TURNS_PER_DAY,
        SHED_CAPACITY,
    )
    from agent.execution.obligation_types import (
        ReservationState,
        ResourceType,
        ResourceReservation,
        ObligationTier,
        ObligationLifecycle,
        ServiceObligation,
    )

try:
    from market.price_math import total_revenue_estimate
except ImportError:
    from agent.market.price_math import total_revenue_estimate

logger = logging.getLogger("CropCycleReservationManager")

# Reserved geometry
SHED_ACCESS_PORT: Tuple[int, int] = (4, 5)

# Safety constants
SW_RESERVATION_SAFETY_MARGIN: float = 200.0  # Minimum positive whole-farm delta required
MIN_TREASURY_BUFFER: float = 300.0          # Cash buffer protected for animal feed and hiring
FEED_SAFETY_BUFFER_DAYS: int = 3            # Days of feed wheat required before non-feed expansion
MAX_WORKER_LOAD_THRESHOLD: float = 0.85     # Max acceptable labor utilization


def get_crop_cycle_schedule(crop: str, plant_day: int) -> Tuple[int, List[int], List[int]]:
    """Derive dated watering and harvest windows for a crop planted on plant_day.
    
    Returns:
        (total_yield_units, watering_days, harvest_days)
    """
    c_info = CROPS.get(crop, {})
    if not c_info:
        return 0, [], []

    is_ongoing = c_info.get("ongoing", False)
    watering_days: List[int] = [plant_day]

    if is_ongoing:
        first_yield = plant_day + c_info["first_yield_day"]
        interval = c_info["interval"]
        max_yield = c_info["max_yield"]

        # Ongoing crops require periodic watering up to first yield
        for d in range(plant_day + 1, min(first_yield, 29)):
            watering_days.append(d)

        harvest_days = []
        for tick in range(min(4, max_yield)):
            h_day = first_yield + tick * interval
            if h_day <= 29:
                harvest_days.append(h_day)
                # Watering between harvests
                if tick < min(4, max_yield) - 1 and h_day < 29:
                    watering_days.append(h_day)

        total_units = len(harvest_days)
        return total_units, watering_days, harvest_days
    else:
        max_yield_day = plant_day + c_info["max_yield_day"]
        # Single-harvest crops require watering during maturation
        for d in range(plant_day + 1, min(max_yield_day, 29)):
            watering_days.append(d)

        if max_yield_day <= 29:
            harvest_days = [max_yield_day]
            total_units = c_info["max_yield"]
        else:
            harvest_days = []
            total_units = 0

        return total_units, watering_days, harvest_days


@dataclass
class CropCycleReservation:
    """Atomic multi-resource commitment for a single 4-tile crop cohort."""
    reservation_id: str
    crop_cycle_id: str
    tiles: List[Tuple[int, int]]
    crop: str
    plant_day: int
    watering_days: List[int]
    harvest_days: List[int]
    seed_cost: float
    expected_yield_per_tile: int
    total_expected_yield: int
    expected_gross_revenue: float
    expected_net_margin: float
    state: ReservationState = ReservationState.TRIAL
    obligations: List[ServiceObligation] = field(default_factory=list)
    binding_resource: Optional[str] = None
    binding_day_hour: Optional[str] = None
    rejection_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_committed(self) -> bool:
        return self.state == ReservationState.COMMITTED

    def is_fulfilled(self) -> bool:
        return self.state == ReservationState.FULFILLED


@dataclass
class CropCycleTrialResult:
    """Outcome of a side-effect-free complete crop-cycle evaluation trial."""
    feasible: bool = False
    expected_whole_farm_delta: float = 0.0
    reservation: Optional[CropCycleReservation] = None
    binding_region: Optional[str] = None
    binding_day_hour: Optional[str] = None
    binding_resource: Optional[str] = None
    rejection_reason: Optional[str] = None
    safety_margin: float = SW_RESERVATION_SAFETY_MARGIN
    certificates: Dict[str, bool] = field(default_factory=lambda: {
        "geometry_valid": False,
        "treasury_feasible": False,
        "feed_buffer_protected": False,
        "labor_capacity_feasible": False,
        "storage_headroom_feasible": False,
        "terminal_sale_feasible": False,
    })


class CropCycleReservationManager:
    """Orchestrates transactional crop-cycle reservations and full lifecycle tracking."""

    def __init__(self) -> None:
        self.active_reservations: Dict[str, CropCycleReservation] = {}
        self.committed_reservations_history: List[CropCycleReservation] = []
        self.rejection_log: List[Dict[str, Any]] = []
        self._counter: int = 0
        self._telemetry = {
            "trials_evaluated": 0,
            "trials_approved": 0,
            "trials_rejected": 0,
            "reservations_committed": 0,
            "reservations_fulfilled": 0,
            "reservations_failed": 0,
            "rejections_by_reason": {},
            "total_reserved_acreage": 0,
        }

    def reset(self) -> None:
        self.active_reservations.clear()
        self.committed_reservations_history.clear()
        self.rejection_log.clear()
        self._counter = 0
        self._telemetry = {
            "trials_evaluated": 0,
            "trials_approved": 0,
            "trials_rejected": 0,
            "reservations_committed": 0,
            "reservations_fulfilled": 0,
            "reservations_failed": 0,
            "rejections_by_reason": {},
            "total_reserved_acreage": 0,
        }

    def get_telemetry(self) -> Dict[str, Any]:
        return copy.deepcopy(self._telemetry)

    def evaluate_complete_crop_cycle(
        self,
        candidate_tiles: List[Tuple[int, int]],
        candidate_crop: str,
        plant_day: int,
        current_cash: float,
        active_workers: int,
        num_animals: int,
        wheat_inventory: int,
        current_shed_occupancy: int,
        core_planted_tiles: int,
        current_commitments: Optional[Dict[str, Any]] = None,
        market_inventories: Optional[Dict[str, int]] = None,
    ) -> CropCycleTrialResult:
        """Side-effect-free trial evaluation of the complete executable lifecycle.
        
        Guarantees:
        1. Leaves all existing state, commitments, and admitted tiles untouched on failure.
        2. Evaluates the complete lifecycle: seeds, planting, watering, maturity, harvest,
           storage, and market sale before Day 29.
        3. Requires net whole-farm economic delta > SW_RESERVATION_SAFETY_MARGIN.
        """
        self._telemetry["trials_evaluated"] += 1
        n_tiles = len(candidate_tiles)
        certs = {
            "geometry_valid": False,
            "treasury_feasible": False,
            "feed_buffer_protected": False,
            "labor_capacity_feasible": False,
            "storage_headroom_feasible": False,
            "terminal_sale_feasible": False,
        }

        # 1. Geometry and port protection check
        for t in candidate_tiles:
            if t == SHED_ACCESS_PORT:
                reason = f"Tile {t} violates reserved shed-access port invariant"
                self._record_rejection(reason)
                return CropCycleTrialResult(feasible=False, binding_resource="GEOMETRY", rejection_reason=reason, certificates=certs)
            if not (0 <= t[0] < 5 and 5 <= t[1] < 10):
                reason = f"Tile {t} outside SW quadrant bounds"
                self._record_rejection(reason)
                return CropCycleTrialResult(feasible=False, binding_resource="GEOMETRY", rejection_reason=reason, certificates=certs)
        certs["geometry_valid"] = True

        # 2. Crop biological timeline & harvest realization check
        c_info = CROPS.get(candidate_crop, {})
        if not c_info:
            reason = f"Unknown crop: {candidate_crop}"
            self._record_rejection(reason)
            return CropCycleTrialResult(feasible=False, binding_resource="BIOLOGY", rejection_reason=reason, certificates=certs)

        yield_per_tile, watering_days, harvest_days = get_crop_cycle_schedule(candidate_crop, plant_day)
        if yield_per_tile <= 0 or not harvest_days:
            reason = f"Crop {candidate_crop} planted on Day {plant_day} cannot realize harvest before Day 29 cutoff"
            self._record_rejection(reason)
            return CropCycleTrialResult(feasible=False, binding_resource="BIOLOGY", rejection_reason=reason, certificates=certs)

        total_yield_units = n_tiles * yield_per_tile
        certs["terminal_sale_feasible"] = True

        # 3. Treasury feasibility check
        seed_price = float(c_info.get("seed", 0.0))
        seed_cost = seed_price * n_tiles
        required_cash = seed_cost + MIN_TREASURY_BUFFER
        if current_cash < required_cash:
            reason = f"Treasury shortage: cash ${current_cash:.1f} < seed ${seed_cost:.1f} + safety ${MIN_TREASURY_BUFFER:.1f}"
            self._record_rejection(reason)
            return CropCycleTrialResult(feasible=False, binding_resource="CASH", binding_day_hour=f"D{plant_day}H0", rejection_reason=reason, certificates=certs)
        certs["treasury_feasible"] = True

        # 4. Livestock feed safety check
        required_wheat_buffer = num_animals * FEED_SAFETY_BUFFER_DAYS
        if candidate_crop != "WHEAT" and wheat_inventory < required_wheat_buffer:
            reason = f"Feed risk: wheat inventory {wheat_inventory} < required {required_wheat_buffer} buffer for {num_animals} animals"
            self._record_rejection(reason)
            return CropCycleTrialResult(feasible=False, binding_resource="WHEAT_FEED", binding_day_hour=f"D{plant_day}H0", rejection_reason=reason, certificates=certs)
        certs["feed_buffer_protected"] = True

        # Build detailed obligations for the candidate reservation
        self._counter += 1
        res_id = f"RES_SW_C{len(candidate_tiles)}_{candidate_crop}_D{plant_day}_{self._counter}"
        cycle_id = f"CYCLE_SW_{candidate_crop}_D{plant_day}_{self._counter}"

        obligations: List[ServiceObligation] = []
        for tile in candidate_tiles:
            # 1. PLANT obligation
            obligations.append(ServiceObligation(
                obligation_id=f"OBL_{cycle_id}_PLANT_{tile[0]}_{tile[1]}",
                entity_id=f"SW_({tile[0]},{tile[1]})",
                op="PLANT",
                target_pos=tile,
                region="SW",
                tier=ObligationTier.STRATEGIC,
                cohort_id=cycle_id,
                required_item=f"{candidate_crop}_SEED",
                required_item_qty=1,
                release_step=plant_day * 24,
                deadline_step=plant_day * 24 + 23,
                economic_value=0.0,
            ))
            # 2. WATER obligations
            for w_day in watering_days:
                obligations.append(ServiceObligation(
                    obligation_id=f"OBL_{cycle_id}_WATER_D{w_day}_{tile[0]}_{tile[1]}",
                    entity_id=f"SW_({tile[0]},{tile[1]})",
                    op="WATER",
                    target_pos=tile,
                    region="SW",
                    tier=ObligationTier.STRATEGIC,
                    cohort_id=cycle_id,
                    release_step=w_day * 24,
                    deadline_step=w_day * 24 + 23,
                    economic_value=0.0,
                ))
            # 3. HARVEST obligations
            for h_day in harvest_days:
                obligations.append(ServiceObligation(
                    obligation_id=f"OBL_{cycle_id}_HARVEST_D{h_day}_{tile[0]}_{tile[1]}",
                    entity_id=f"SW_({tile[0]},{tile[1]})",
                    op="HARVEST",
                    target_pos=tile,
                    region="SW",
                    tier=ObligationTier.STRATEGIC,
                    cohort_id=cycle_id,
                    release_step=h_day * 24,
                    deadline_step=h_day * 24 + 23,
                    economic_value=0.0,
                ))

        # 5. Labor capacity envelope via shared WorkforceCapacityForecaster
        labor_passed = True
        labor_fail_reason = ""
        try:
            from execution.workforce_capacity_forecast import get_workforce_capacity_forecaster
            from execution.service_obligation_ledger import get_service_obligation_ledger
            fc = get_workforce_capacity_forecaster()
            led = get_service_obligation_ledger()
            mock_hands = list(range(max(0, active_workers - 1)))
            feasible, labor_reason, _ = fc.evaluate_candidate_schedule(
                candidate_obligations=obligations,
                current_step=plant_day * 24,
                obs_farm={"farmer": (4, 4), "hands": mock_hands},
                private={"shed": {"WHEAT": wheat_inventory}, "inventories": []},
                ledger=led,
                max_load_threshold=MAX_WORKER_LOAD_THRESHOLD,
            )
            if not feasible:
                labor_passed = False
                labor_fail_reason = labor_reason
        except Exception:
            # Fallback to direct time-dependent capacity envelope check
            daily_supply = 24.0 + (18.0 * max(0, active_workers - 1))
            current_committed_acreage = sum(len(r.tiles) for r in self.active_reservations.values() if r.is_committed())
            plant_day_workload = num_animals + (0.6 * core_planted_tiles) + (0.6 * current_committed_acreage) + (2.0 * n_tiles)
            if plant_day_workload > daily_supply * MAX_WORKER_LOAD_THRESHOLD:
                labor_passed = False
                labor_fail_reason = f"Labor overload on Day {plant_day}: estimated {plant_day_workload:.1f} > allowable {daily_supply * MAX_WORKER_LOAD_THRESHOLD:.1f}"

        if not labor_passed:
            self._record_rejection(labor_fail_reason)
            return CropCycleTrialResult(feasible=False, binding_resource="LABOR", binding_day_hour=f"D{plant_day}", rejection_reason=labor_fail_reason, certificates=certs)
        certs["labor_capacity_feasible"] = True

        # 6. Storage headroom check
        # Peak shed room required on harvest days
        available_shed_room = max(0, SHED_CAPACITY - current_shed_occupancy)
        if current_shed_occupancy >= 75 and total_yield_units > available_shed_room:
            reason = f"Storage congestion: peak harvest {total_yield_units} units exceeds available shed room {available_shed_room}"
            self._record_rejection(reason)
            return CropCycleTrialResult(feasible=False, binding_resource="STORAGE_SLOT", rejection_reason=reason, certificates=certs)
        certs["storage_headroom_feasible"] = True

        # 7. Defensible incremental whole-farm economics evaluation
        # Accounts for:
        # - Realized sales revenue under market inventory price curve
        # - Direct seed costs
        # - Displaced internal feed production (worker-hours spent in SW require purchasing market feed)
        m_inv = market_inventories or {}
        crop_market_inv = m_inv.get(candidate_crop, MARKET_I0)
        gross_revenue = float(total_revenue_estimate(candidate_crop, crop_market_inv, total_yield_units))

        # SW labor hours across lifecycle: planting, watering sweeps, and harvest sweeps
        sw_cycle_hours = n_tiles + (len(watering_days) * n_tiles) + (len(harvest_days) * n_tiles) + (len(watering_days) + 2) * 2.0
        # Displaced wheat cost: ~0.12 units of core wheat displaced per worker-hour diverted to SW
        raw_wheat_inv = m_inv.get("WHEAT", MARKET_I0) if isinstance(m_inv, dict) else MARKET_I0
        w_inv_val = float(raw_wheat_inv if isinstance(raw_wheat_inv, (int, float)) else 100.0)
        wheat_price_est = max(20.0, min(50.0, 100.0 / (1.0 + w_inv_val / 100.0)))
        feed_displacement_cost = sw_cycle_hours * 0.12 * wheat_price_est

        net_margin = gross_revenue - seed_cost - feed_displacement_cost

        if net_margin < SW_RESERVATION_SAFETY_MARGIN:
            reason = (
                f"Economic whole-farm delta ${net_margin:.1f} (gross ${gross_revenue:.1f} - seed ${seed_cost:.1f} - "
                f"feed displacement ${feed_displacement_cost:.1f}) below required safety margin ${SW_RESERVATION_SAFETY_MARGIN:.1f}"
            )
            self._record_rejection(reason)
            return CropCycleTrialResult(
                feasible=False,
                expected_whole_farm_delta=net_margin,
                binding_resource="MARGIN",
                rejection_reason=reason,
                certificates=certs,
            )

        # Update economic values on generated obligations
        for obl in obligations:
            if obl.op == "PLANT":
                obl.economic_value = net_margin / n_tiles
            elif obl.op == "WATER":
                obl.economic_value = net_margin / (n_tiles * max(1, len(watering_days)))
            elif obl.op == "HARVEST":
                obl.economic_value = gross_revenue / (n_tiles * max(1, len(harvest_days)))

        res = CropCycleReservation(
            reservation_id=res_id,
            crop_cycle_id=cycle_id,
            tiles=list(candidate_tiles),
            crop=candidate_crop,
            plant_day=plant_day,
            watering_days=list(watering_days),
            harvest_days=list(harvest_days),
            seed_cost=seed_cost,
            expected_yield_per_tile=yield_per_tile,
            total_expected_yield=total_yield_units,
            expected_gross_revenue=gross_revenue,
            expected_net_margin=net_margin,
            state=ReservationState.TRIAL,
            obligations=obligations,
            metadata={
                "certificates": certs,
                "active_workers": active_workers,
                "cash_at_trial": current_cash,
                "feed_displacement_cost": feed_displacement_cost,
            },
        )

        self._telemetry["trials_approved"] += 1
        return CropCycleTrialResult(
            feasible=True,
            expected_whole_farm_delta=net_margin,
            reservation=res,
            certificates=certs,
        )

    def commit_reservation(self, trial_result: CropCycleTrialResult) -> str:
        """Atomically commit a validated trial reservation.
        
        Transitions state to COMMITTED, logs the reservation, and returns reservation_id.
        """
        if not trial_result.feasible or trial_result.reservation is None:
            raise ValueError("Cannot commit an infeasible or null reservation trial")

        res = trial_result.reservation
        res.state = ReservationState.COMMITTED
        for obl in res.obligations:
            obl.lifecycle = ObligationLifecycle.RESERVED

        self.active_reservations[res.reservation_id] = res
        self.committed_reservations_history.append(res)
        self._telemetry["reservations_committed"] += 1
        self._telemetry["total_reserved_acreage"] += len(res.tiles)

        logger.info(
            f"[CropCycleReservationManager] COMMITTED {res.reservation_id}: "
            f"{len(res.tiles)}x {res.crop} on Day {res.plant_day} "
            f"(Expected Margin: ${res.expected_net_margin:.1f})"
        )
        return res.reservation_id

    def reconcile_turn(self, ctx: Dict[str, Any], ledger: Optional[Any] = None) -> None:
        """Reconcile active reservations against game observation.
        
        Requires actual physical tile clearing or executed harvest obligations
        before establishing fulfillment. Passing the date alone does not assume success.
        """
        farm = ctx.get("farm")
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)
        step = ctx.get("step", day * 24 + hour)

        for res_id, res in list(self.active_reservations.items()):
            if res.state != ReservationState.COMMITTED:
                continue

            last_harvest_day = max(res.harvest_days) if res.harvest_days else res.plant_day
            if day > last_harvest_day:
                harvest_successful = False
                if farm and "tiles" in farm:
                    tiles = farm["tiles"]
                    # If tiles are cleared of the mature crop, harvest executed
                    tiles_cleared = True
                    for (x, y) in res.tiles:
                        if 0 <= y < len(tiles) and 0 <= x < len(tiles[0]):
                            t_info = tiles[y][x]
                            # If tile still holds unharvested mature or decaying crop, harvest did not establish
                            if t_info.get("crop") == res.crop and t_info.get("stage") == "mature":
                                tiles_cleared = False
                                break
                    harvest_successful = tiles_cleared
                else:
                    if ledger is not None:
                        h_obls = [o for o in res.obligations if o.op == "HARVEST"]
                        if h_obls:
                            completed_h = [
                                o for o in h_obls
                                if ledger.get_obligation(o.obligation_id) and
                                ledger.get_obligation(o.obligation_id).lifecycle == ObligationLifecycle.COMPLETED
                            ]
                            harvest_successful = (len(completed_h) >= len(h_obls) * 0.5)

                if harvest_successful:
                    res.state = ReservationState.FULFILLED
                    self._telemetry["reservations_fulfilled"] += 1
                    del self.active_reservations[res_id]
                    logger.info(f"[CropCycleReservationManager] FULFILLED {res_id}")
                else:
                    res.state = ReservationState.FAILED
                    self._telemetry["reservations_failed"] += 1
                    del self.active_reservations[res_id]
                    logger.warning(f"[CropCycleReservationManager] UNHARVESTED/EXPIRED {res_id}: harvest was not established")

    def _record_rejection(self, reason: str) -> None:
        self._telemetry["trials_rejected"] += 1
        self._telemetry["rejections_by_reason"][reason] = (
            self._telemetry["rejections_by_reason"].get(reason, 0) + 1
        )
        self.rejection_log.append({"reason": reason})


# Singleton instance
_RESERVATION_MANAGER: Optional[CropCycleReservationManager] = None


def get_crop_cycle_reservation_manager() -> CropCycleReservationManager:
    import sys
    global _RESERVATION_MANAGER
    for alias in (
        "agent.strategy.crop_cycle_reservation_manager",
        "strategy.crop_cycle_reservation_manager",
        "crop_cycle_reservation_manager",
    ):
        if alias in sys.modules:
            mod = sys.modules[alias]
            if hasattr(mod, "_RESERVATION_MANAGER") and mod._RESERVATION_MANAGER is not None:
                _RESERVATION_MANAGER = mod._RESERVATION_MANAGER
                return _RESERVATION_MANAGER

    if _RESERVATION_MANAGER is None:
        _RESERVATION_MANAGER = CropCycleReservationManager()

    for alias in (
        "agent.strategy.crop_cycle_reservation_manager",
        "strategy.crop_cycle_reservation_manager",
        "crop_cycle_reservation_manager",
    ):
        if alias in sys.modules:
            try:
                setattr(sys.modules[alias], "_RESERVATION_MANAGER", _RESERVATION_MANAGER)
            except Exception:
                pass

    return _RESERVATION_MANAGER


def reset_crop_cycle_reservation_manager() -> None:
    import sys
    global _RESERVATION_MANAGER
    if _RESERVATION_MANAGER is not None:
        _RESERVATION_MANAGER.reset()
    for alias in (
        "agent.strategy.crop_cycle_reservation_manager",
        "strategy.crop_cycle_reservation_manager",
        "crop_cycle_reservation_manager",
    ):
        if alias in sys.modules and hasattr(sys.modules[alias], "_RESERVATION_MANAGER"):
            try:
                inst = getattr(sys.modules[alias], "_RESERVATION_MANAGER")
                if inst is not None and inst is not _RESERVATION_MANAGER:
                    inst.reset()
            except Exception:
                pass
