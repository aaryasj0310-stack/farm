"""Treatment-Only SW Tranche Controller.

Part of Kaggriculture Phase B1: True Branch-Point SW Treatment Experiment.
Enforces the Phase B0 counterfactual policy in the real engine:
1. Suppresses baseline early SW purchase before WholeFarmPlanner certification.
2. Authorizes engine BUY_LAND order when WholeFarmPlanner approves PURCHASE.
3. Restricts SW planting strictly to the admitted compact tranche tiles.
4. Enforces the invariant: active SW planted tiles <= admitted SW tile set.
5. Tracks utilization, economics, and core farm safety metrics.
"""
from __future__ import annotations

import copy
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# Bidirectional module aliasing to guarantee singleton state across import paths
_mod_name = __name__
if _mod_name.startswith("agent."):
    _bare_name = _mod_name[6:]
    sys.modules.setdefault(_bare_name, sys.modules[_mod_name])
    _pkg_parts = _bare_name.split(".")
    if len(_pkg_parts) > 1 and _pkg_parts[0] in sys.modules:
        setattr(sys.modules[_pkg_parts[0]], _pkg_parts[1], sys.modules[_mod_name])
else:
    _agent_name = f"agent.{_mod_name}"
    sys.modules.setdefault(_agent_name, sys.modules[_mod_name])
    _pkg_parts = _mod_name.split(".")
    _agent_pkg = f"agent.{_pkg_parts[0]}"
    if "agent" in sys.modules:
        if _agent_pkg not in sys.modules and _pkg_parts[0] in sys.modules:
            sys.modules[_agent_pkg] = sys.modules[_pkg_parts[0]]
        if _agent_pkg in sys.modules:
            setattr(sys.modules[_agent_pkg], _pkg_parts[1], sys.modules[_mod_name])
            setattr(sys.modules["agent"], _pkg_parts[0], sys.modules[_agent_pkg])

logger = logging.getLogger(__name__)

# All 25 SW coordinates on 10x10 board: x in [0, 4], y in [5, 9]
SW_COORDINATES: Set[Tuple[int, int]] = {
    (x, y) for x in range(5) for y in range(5, 10)
}
SW_PORT: Tuple[int, int] = (4, 5)


@dataclass
class SWLandLifecycleTelemetry:
    """Rigorous 9-stage lifecycle telemetry for SW land acquisition."""
    # Stage 1: SW recommendation
    sw_recommendation_step: Optional[int] = None
    sw_recommendation_day: Optional[int] = None
    sw_recommendation_hour: Optional[int] = None

    # Stage 2: Admission approved
    sw_approved_step: Optional[int] = None
    sw_approved_day: Optional[int] = None
    sw_approved_hour: Optional[int] = None

    # Stage 3: SW purchase intent created
    sw_intent_created_step: Optional[int] = None

    # Stage 4: SW purchase order emitted
    sw_order_emitted_step: Optional[int] = None
    sw_order_emitted_day: Optional[int] = None
    sw_order_emitted_hour: Optional[int] = None
    sw_order_emitted_count: int = 0

    # Stage 5: Order retained after shared 10-slot market arbitration
    sw_order_retained_step: Optional[int] = None
    sw_order_retained_slot_index: Optional[int] = None

    # Stage 6: Engine-confirmed SW ownership
    sw_confirmed_step: Optional[int] = None
    sw_confirmed_day: Optional[int] = None
    sw_confirmed_hour: Optional[int] = None
    sw_confirmed_cash_deduction: float = 0.0

    # Settlement telemetry (SW-C2-R2)
    exact_purchase_step: Optional[int] = None
    exact_purchase_day: Optional[int] = None
    exact_purchase_hour: Optional[int] = None
    cash_before_purchase: float = 0.0
    cash_after_purchase: float = 0.0
    purchase_settled: bool = False
    purchase_attempt_steps: List[int] = field(default_factory=list)

    # Stage 7: Purchase failed or dropped
    purchase_failed_events: List[Dict[str, Any]] = field(default_factory=list)

    # Stage 8: Retried purchase
    purchase_retry_count: int = 0
    purchase_retry_steps: List[int] = field(default_factory=list)

    # Stage 9: First productive SW tile planted
    first_productive_plant_step: Optional[int] = None
    first_productive_plant_day: Optional[int] = None
    first_productive_plant_crop: Optional[str] = None
    first_productive_plant_pos: Optional[Tuple[int, int]] = None

    # Quadrant targeting sanity
    targeted_quadrant: str = "SW"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_1_recommendation": {
                "step": self.sw_recommendation_step,
                "day": self.sw_recommendation_day,
                "hour": self.sw_recommendation_hour,
            },
            "stage_2_approval": {
                "step": self.sw_approved_step,
                "day": self.sw_approved_day,
                "hour": self.sw_approved_hour,
            },
            "stage_3_intent_created": {
                "step": self.sw_intent_created_step,
            },
            "stage_4_order_emitted": {
                "step": self.sw_order_emitted_step,
                "day": self.sw_order_emitted_day,
                "hour": self.sw_order_emitted_hour,
                "total_emissions": self.sw_order_emitted_count,
            },
            "stage_5_retained_in_market": {
                "step": self.sw_order_retained_step,
                "slot_index": self.sw_order_retained_slot_index,
            },
            "stage_6_engine_confirmed": {
                "step": self.sw_confirmed_step,
                "day": self.sw_confirmed_day,
                "hour": self.sw_confirmed_hour,
                "cash_deduction": self.sw_confirmed_cash_deduction,
            },
            "settlement_telemetry": {
                "exact_purchase_step": self.exact_purchase_step,
                "exact_purchase_day": self.exact_purchase_day,
                "exact_purchase_hour": self.exact_purchase_hour,
                "cash_before_purchase": self.cash_before_purchase,
                "cash_after_purchase": self.cash_after_purchase,
                "purchase_settled": self.purchase_settled,
                "purchase_attempt_steps": list(self.purchase_attempt_steps),
            },
            "stage_7_purchase_failed_events": list(self.purchase_failed_events),
            "stage_8_retried_purchases": {
                "retry_count": self.purchase_retry_count,
                "retry_steps": list(self.purchase_retry_steps),
            },
            "stage_9_first_productive_plant": {
                "step": self.first_productive_plant_step,
                "day": self.first_productive_plant_day,
                "crop": self.first_productive_plant_crop,
                "pos": list(self.first_productive_plant_pos) if self.first_productive_plant_pos else None,
            },
            "targeted_quadrant": self.targeted_quadrant,
        }


@dataclass
class CropProvenanceTracker:
    """Auditable tile-level physical provenance and revenue attribution tracker."""
    core_harvested_units: Dict[str, int] = field(default_factory=dict)
    sw_harvested_units: Dict[str, int] = field(default_factory=dict)
    core_planted_units: Dict[str, int] = field(default_factory=dict)
    sw_planted_units: Dict[str, int] = field(default_factory=dict)
    total_sales_units: Dict[str, int] = field(default_factory=dict)
    total_sales_revenue: Dict[str, float] = field(default_factory=dict)
    individual_sales: Dict[str, List[Tuple[int, int, float]]] = field(default_factory=dict)  # (step, units, price)
    ending_shed_units: Dict[str, int] = field(default_factory=dict)
    ending_worker_units: Dict[str, int] = field(default_factory=dict)
    discarded_overflow_units: Dict[str, int] = field(default_factory=dict)

    def record_harvest(self, pos: Tuple[int, int], crop: str, units: int) -> None:
        """Record harvest distinguished by physical tile coordinates."""
        is_sw = (pos[0] < 5 and pos[1] >= 5)
        if is_sw:
            self.sw_harvested_units[crop] = self.sw_harvested_units.get(crop, 0) + units
        else:
            self.core_harvested_units[crop] = self.core_harvested_units.get(crop, 0) + units

    def record_sale(self, step: int, crop: str, units: int, unit_price: float) -> None:
        """Record executed market sale."""
        self.total_sales_units[crop] = self.total_sales_units.get(crop, 0) + units
        rev = float(units * unit_price)
        self.total_sales_revenue[crop] = self.total_sales_revenue.get(crop, 0.0) + rev
        self.individual_sales.setdefault(crop, []).append((step, units, unit_price))

    def get_provenance_attribution(self, crop: str) -> Dict[str, Any]:
        """Compute exact physical provenance bounds and proportional attribution."""
        h_sw = self.sw_harvested_units.get(crop, 0)
        h_core = self.core_harvested_units.get(crop, 0)
        s_total = self.total_sales_units.get(crop, 0)
        rev_total = self.total_sales_revenue.get(crop, 0.0)
        avg_price = (rev_total / s_total) if s_total > 0 else 0.0

        # Provenance bounds
        upper_sw_units = min(h_sw, s_total)
        lower_sw_units = max(0, s_total - h_core)
        h_sum = h_sw + h_core
        prop_sw_units = (s_total * (h_sw / h_sum)) if h_sum > 0 else 0.0

        upper_rev = upper_sw_units * avg_price
        lower_rev = lower_sw_units * avg_price
        prop_rev = prop_sw_units * avg_price

        shed_end = self.ending_shed_units.get(crop, 0)
        worker_end = self.ending_worker_units.get(crop, 0)
        discarded = self.discarded_overflow_units.get(crop, 0)

        # Conservation check: harvested == sales + shed + worker + discarded
        accounted = s_total + shed_end + worker_end + discarded
        conservation_verified = (h_sum == accounted)

        return {
            "crop": crop,
            "core_harvested_units": h_core,
            "sw_harvested_units": h_sw,
            "total_harvested_units": h_sum,
            "total_sold_units": s_total,
            "total_sold_revenue": round(rev_total, 2),
            "average_realized_price": round(avg_price, 2),
            "sw_sales_upper_bound_units": upper_sw_units,
            "sw_sales_lower_bound_units": lower_sw_units,
            "sw_sales_proportional_units": round(prop_sw_units, 2),
            "sw_revenue_upper_bound": round(upper_rev, 2),
            "sw_revenue_lower_bound": round(lower_rev, 2),
            "sw_revenue_proportional": round(prop_rev, 2),
            "ending_shed_units": shed_end,
            "ending_worker_units": worker_end,
            "discarded_overflow_units": discarded,
            "conservation_verified": conservation_verified,
        }


@dataclass
class SWTrancheState:
    """State of the SW tranche controller for a single match."""
    treatment_active: bool = False
    sw_purchase_recommended: bool = False
    sw_purchase_approved: bool = False
    sw_land_order_emitted: bool = False
    sw_purchase_confirmed: bool = False
    sw_unlock_observed: bool = False
    purchase_failed_reason: Optional[str] = None
    sw_purchase_day: Optional[int] = None
    sw_purchase_hour: Optional[int] = None
    selected_portfolio: Optional[Dict[str, Any]] = None
    selected_portfolio_name: Optional[str] = None
    admitted_sw_tiles: Set[Tuple[int, int]] = field(default_factory=set)
    admitted_sw_crop_targets: Dict[Tuple[int, int], str] = field(default_factory=dict)
    predicted_delta_fc: float = 0.0
    pre_purchase_cash: float = 0.0
    post_purchase_cash: float = 0.0
    worker_count_at_purchase: int = 0
    sw_reservation_id: Optional[str] = None
    sw_reservation_ids: List[str] = field(default_factory=list)

    # 9-Stage Land Order Lifecycle Telemetry
    lifecycle: SWLandLifecycleTelemetry = field(default_factory=SWLandLifecycleTelemetry)

    # Auditable Tile-Level Physical Provenance Tracker
    provenance: CropProvenanceTracker = field(default_factory=CropProvenanceTracker)

    # Economics & operations tracking
    sw_land_cost_paid: float = 0.0
    sw_seed_cost_realized: float = 0.0
    sw_seeds_bought_with_cash: Dict[str, int] = field(default_factory=dict)
    sw_seed_inventory_consumed: Dict[str, int] = field(default_factory=dict)
    sw_seed_opportunity_cost: float = 0.0
    sw_crops_planted: Dict[str, int] = field(default_factory=dict)
    sw_crops_harvested: Dict[str, int] = field(default_factory=dict)
    sw_crops_sold: Dict[str, int] = field(default_factory=dict)
    sw_revenue_realized: float = 0.0
    total_farm_portfolio_sales: Dict[str, int] = field(default_factory=dict)
    total_farm_portfolio_revenue: float = 0.0
    estimated_sw_origin_revenue: float = 0.0
    unattributable_mixed_origin_revenue: float = 0.0

    # Utilization checkpoints relative to purchase day: "D+0", "D+1", "D+2", "D+3", "D+5", "D+7"
    checkpoints: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Rejection reasons for turns when SW purchase was evaluated but rejected/delayed
    rejection_reasons_by_day: Dict[int, List[str]] = field(default_factory=dict)
    primary_no_purchase_reason: Optional[str] = None

    # Safety & invariant violations attempted/prevented
    invariant_violations_attempted: int = 0

    # Core farm safety tracking
    core_watered_count: int = 0
    core_harvest_count: int = 0
    animals_fed_total: int = 0
    animal_loss_events: int = 0
    min_feed_wheat_balance: int = 9999
    peak_daily_actions: int = 0
    peak_shed_usage: int = 0

    # Phase SW-C1: Adaptive Acreage Expansion Telemetry
    max_admitted_acreage: int = 8
    last_expansion_day: int = -1
    adaptive_expansion_history: List[Dict[str, Any]] = field(default_factory=list)
    expansion_rejections: List[Dict[str, Any]] = field(default_factory=list)


class SWTrancheController:
    """Singleton controller managing SW branch treatment execution."""

    def __init__(self) -> None:
        self.state = SWTrancheState()

    def reset(self) -> None:
        """Reset state cleanly between matches."""
        self.state = SWTrancheState()

    def set_treatment_active(self, active: bool) -> None:
        """Explicitly enable or disable treatment mode."""
        self.state.treatment_active = bool(active)

    def is_treatment_active(self) -> bool:
        """Check if treatment mode is active."""
        if self.state.treatment_active:
            return True
        try:
            from config import get_sw_forward_architecture_mode
            return get_sw_forward_architecture_mode() == "TREATMENT"
        except Exception:
            return False

    def should_suppress_baseline_sw_buy(self, day: int, hour: int, farm: Any) -> bool:
        """Check if baseline BUY_LAND for SW should be suppressed."""
        if not self.is_treatment_active():
            return False
        # Suppress baseline buy if WholeFarmPlanner has not approved SW purchase
        return not self.state.sw_purchase_approved

    def evaluate_and_check_sw_purchase(
        self,
        ctx: Dict[str, Any],
        plan: Any,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Evaluate WholeFarmPlanner for SW purchase admission in treatment mode.

        Returns (approved, selected_portfolio_dict).
        """
        if not self.is_treatment_active():
            return False, None

        if self.state.sw_purchase_approved:
            # Already approved in an earlier hour/day
            return True, self.state.selected_portfolio

        farm = ctx.get("farm")
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)

        # If SW is already unlocked in engine, no need to purchase
        if farm and hasattr(farm, "unlocked") and "SW" in farm.unlocked:
            return False, None

        # Enforce effective quadrant unlock day
        try:
            from strategy.expansion_planner import get_effective_quadrant_unlock_day
            unlock_day = get_effective_quadrant_unlock_day(3)
        except Exception:
            unlock_day = 9
        if day < unlock_day:
            reason = f"before_unlock_day_{unlock_day}"
            day_reasons = self.state.rejection_reasons_by_day.setdefault(day, [])
            day_reasons.append(reason)
            self.state.primary_no_purchase_reason = reason
            return False, None

        # Build snapshot for WholeFarmPlanner evaluation
        try:
            from strategy.whole_farm_planner import ShadowSnapshot, get_whole_farm_planner
            mem = ctx.get("memory", {}) if isinstance(ctx, dict) else {}
            snap = ShadowSnapshot.from_live_state(
                ctx=ctx,
                mem=mem,
                plan=plan,
                asg=None,
                market=[],
            )
            planner = get_whole_farm_planner()
            result = planner.evaluate(snap, raw_ctx=ctx)
            dec = result.decision

            # Check purchase condition
            is_purchase = (
                dec.sw_purchase_recommended
                and dec.sw_recommendation_status == "PURCHASE"
                and dec.combined_cert_feasible
                and dec.lifecycle_workload_feasible
                and dec.portfolio_delta_fc > 0
                and dec.selected_portfolio is not None
            )

            if is_purchase:
                self.approve_purchase(
                    day=day,
                    hour=hour,
                    portfolio=dec.selected_portfolio,
                    delta_fc=dec.portfolio_delta_fc,
                    cash_before=float(farm.money) if farm else snap.money,
                    worker_count=snap.active_worker_count,
                    ctx=ctx,
                )
                return True, dec.selected_portfolio
            else:
                # Record rejection / delay reason
                reason = dec.sw_reject_reason or (
                    dec.disagreements_with_baseline[0].get("reason", dec.sw_recommendation_status)
                    if dec.disagreements_with_baseline else dec.sw_recommendation_status
                )
                day_reasons = self.state.rejection_reasons_by_day.setdefault(day, [])
                day_reasons.append(str(reason))
                self.state.primary_no_purchase_reason = str(reason)
                return False, None

        except Exception as exc:
            logger.warning(f"[SWTrancheController] evaluate_and_check_sw_purchase error: {exc}")
            return False, None

    def approve_purchase(
        self,
        day: int,
        hour: int,
        portfolio: Dict[str, Any],
        delta_fc: float,
        cash_before: float,
        worker_count: int,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Approve SW purchase and freeze the admitted portfolio tranche."""
        self.state.sw_purchase_recommended = True
        self.state.sw_purchase_approved = True
        self.state.sw_purchase_day = day
        self.state.sw_purchase_hour = hour
        self.state.selected_portfolio = copy.deepcopy(portfolio)
        self.state.selected_portfolio_name = portfolio.get("name", "unknown")
        self.state.predicted_delta_fc = float(delta_fc)
        self.state.pre_purchase_cash = float(cash_before)
        self.state.worker_count_at_purchase = int(worker_count)

        # Update 9-stage lifecycle telemetry
        self.state.lifecycle.sw_recommendation_step = day * 24 + hour
        self.state.lifecycle.sw_recommendation_day = day
        self.state.lifecycle.sw_recommendation_hour = hour
        self.state.lifecycle.sw_approved_step = day * 24 + hour
        self.state.lifecycle.sw_approved_day = day
        self.state.lifecycle.sw_approved_hour = hour
        self.state.lifecycle.sw_intent_created_step = day * 24 + hour

        # Freeze admitted coordinates and crop targets
        self.state.admitted_sw_tiles.clear()
        self.state.admitted_sw_crop_targets.clear()

        for alloc in portfolio.get("allocations", []):
            if isinstance(alloc, (list, tuple)) and len(alloc) >= 3:
                crop_name = str(alloc[0])
                tile_list = alloc[2]
                for pos in tile_list:
                    pos_t = (int(pos[0]), int(pos[1]))
                    self.state.admitted_sw_tiles.add(pos_t)
                    self.state.admitted_sw_crop_targets[pos_t] = crop_name
        self.state.max_admitted_acreage = len(self.state.admitted_sw_tiles)

        # Extract real observed farm resources from ctx (eliminate synthetic constants)
        farm = ctx.get("farm") if ctx else None
        private = ctx.get("private") if ctx else None

        num_animals = 0
        core_planted = 0
        if farm and hasattr(farm, "iter_tiles"):
            for t in farm.iter_tiles():
                is_sw = (t.x < 5 and t.y >= 5)
                if getattr(t, "is_animal", False) or getattr(t, "animal", None) is not None:
                    num_animals += 1
                elif not is_sw and (getattr(t, "is_plant", False) or getattr(t, "crop", None) is not None):
                    core_planted += 1

        shed_wheat = 0
        if farm and hasattr(farm, "shed") and hasattr(farm.shed, "inventory"):
            shed_wheat = int(farm.shed.inventory.get("WHEAT", 0))
        carried_wheat = 0
        if private and hasattr(private, "inventories"):
            for inv in private.inventories:
                carried_wheat += int(inv.get("WHEAT", 0))
        elif private and isinstance(private.get("inventories"), list):
            for inv in private.get("inventories", []):
                carried_wheat += int(inv.get("WHEAT", 0))

        in_ground_wheat = 0
        if farm and hasattr(farm, "iter_tiles"):
            for t in farm.iter_tiles():
                is_sw = (t.x < 5 and t.y >= 5)
                if not is_sw and (getattr(t, "is_plant", False) or getattr(t, "kind", "") == "PLANT") and getattr(t, "crop", None) == "WHEAT":
                    in_ground_wheat += 6
        total_real_wheat = shed_wheat + carried_wheat + in_ground_wheat

        shed_occ = 0
        if farm and hasattr(farm, "shed"):
            if hasattr(farm.shed, "num_items"):
                shed_occ = int(farm.shed.num_items)
            elif hasattr(farm.shed, "inventory"):
                shed_occ = sum(int(v) for v in farm.shed.inventory.values())

        # Commit initial tranche reservations for actual mixed portfolio cohorts
        self.state.sw_reservation_ids.clear()
        try:
            from strategy.crop_cycle_reservation_manager import get_crop_cycle_reservation_manager
            res_mgr = get_crop_cycle_reservation_manager()
            allocations = portfolio.get("allocations", [])
            if not allocations and self.state.admitted_sw_tiles:
                primary_crop = next(iter(self.state.admitted_sw_crop_targets.values()), "STRAWBERRY")
                allocations = [(primary_crop, len(self.state.admitted_sw_tiles), list(self.state.admitted_sw_tiles))]

            all_committed_ids = []
            for alloc in allocations:
                c_crop = str(alloc[0])
                c_tiles = [tuple(p) for p in alloc[2]] if len(alloc) >= 3 else list(self.state.admitted_sw_tiles)
                trial = res_mgr.evaluate_complete_crop_cycle(
                    candidate_tiles=c_tiles,
                    candidate_crop=c_crop,
                    plant_day=day,
                    current_cash=cash_before,
                    active_workers=worker_count,
                    num_animals=num_animals,
                    wheat_inventory=total_real_wheat,
                    current_shed_occupancy=shed_occ,
                    core_planted_tiles=core_planted,
                )
                if trial.feasible:
                    res_id = res_mgr.commit_reservation(trial)
                    all_committed_ids.append(res_id)
                else:
                    logger.warning(f"[SWTrancheController] Cohort {c_crop} reservation infeasible: {trial.rejection_reason}")

            if all_committed_ids:
                self.state.sw_reservation_ids = all_committed_ids
                self.state.sw_reservation_id = all_committed_ids[0]
        except Exception as exc:
            logger.debug(f"[SWTrancheController] Initial tranche reservation note: {exc}")

    def maybe_evaluate_adaptive_expansion(
        self,
        ctx: Dict[str, Any],
        farm: Any,
        plan: Any,
    ) -> Optional[Any]:
        """Evaluate and apply Phase SW-C1 adaptive acreage expansion if eligible.

        Called at macro planning turns. Only executes when:
        1. Treatment is active
        2. SW_ADAPTIVE_ACREAGE_ENABLED is True
        3. SW quadrant is unlocked and purchase confirmed
        4. Day > sw_purchase_day (initial 8-tile tranche already established)
        5. Hour == 0 (daily morning planning turn)
        6. Current acreage < SW_MAX_ADAPTIVE_ACREAGE
        7. Expansion has not already been evaluated/applied on current_day
        """
        if not self.is_treatment_active():
            return None

        try:
            from config import get_sw_adaptive_acreage_enabled, get_sw_max_adaptive_acreage
            adaptive_enabled = get_sw_adaptive_acreage_enabled()
            max_acreage_cap = get_sw_max_adaptive_acreage()
        except ImportError:
            try:
                from agent.config import get_sw_adaptive_acreage_enabled, get_sw_max_adaptive_acreage
                adaptive_enabled = get_sw_adaptive_acreage_enabled()
                max_acreage_cap = get_sw_max_adaptive_acreage()
            except Exception:
                adaptive_enabled = False
                max_acreage_cap = 24

        if not adaptive_enabled:
            return None

        # SW must be confirmed and unlocked
        is_unlocked = (farm and hasattr(farm, "unlocked") and "SW" in farm.unlocked) or self.state.sw_purchase_confirmed
        if not is_unlocked:
            return None

        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)

        # Only evaluate at day start (hour == 0) and strictly after the purchase day
        if hour != 0:
            return None

        # Must not expand on the purchase day itself (preserves initial 8-tile tranche)
        purchase_day = self.state.sw_purchase_day if self.state.sw_purchase_day is not None else 8
        if day <= purchase_day:
            return None

        # Must not expand more than once per day
        if self.state.last_expansion_day == day:
            return None

        current_acreage = len(self.state.admitted_sw_tiles)
        if current_acreage >= max_acreage_cap:
            return None

        # Gather state metrics for capacity certificate evaluation (supporting both FarmView and raw dict)
        if farm is not None:
            if isinstance(farm, dict):
                current_cash = float(farm.get("money", 0.0))
                hands_list = farm.get("hands", []) or []
                raw_tiles = farm.get("tiles", []) or []
            else:
                current_cash = float(getattr(farm, "money", 0.0))
                hands_list = getattr(farm, "hands", []) or []
                raw_tiles = getattr(farm, "tiles_raw", getattr(farm, "tiles", [])) or []
        else:
            current_cash = 0.0
            hands_list = []
            raw_tiles = []

        # Use strictly executable workforce: farmer (1) + physically present hired hands
        active_workers = 1 + len(hands_list)

        # Count animals and core planted tiles
        num_animals = 0
        core_planted = 0
        if farm is not None and hasattr(farm, "iter_tiles"):
            for t in farm.iter_tiles():
                is_sw = (t.x < 5 and t.y >= 5)
                if getattr(t, "is_animal", False) or getattr(t, "animal", None) is not None:
                    num_animals += 1
                elif not is_sw and getattr(t, "is_plant", False):
                    core_planted += 1
        elif raw_tiles:
            for y, row in enumerate(raw_tiles):
                for x, cell in enumerate(row):
                    is_sw = (x < 5 and y >= 5)
                    if isinstance(cell, dict):
                        is_anim = cell.get("kind") in ("COW", "SHEEP", "CHICKEN", "GOOSE", "PASTURE") or cell.get("animal") is not None
                        is_pl = cell.get("kind") == "PLANT"
                        if is_anim:
                            num_animals += 1
                        elif not is_sw and is_pl:
                            core_planted += 1

        private = ctx.get("private")
        if private is not None:
            if isinstance(private, dict):
                shed_inv = private.get("shed", {}) or {}
            else:
                shed_inv = getattr(private, "shed", {}) or {}
        else:
            shed_inv = {}

        wheat_inventory = int(shed_inv.get("WHEAT", 0))
        shed_units = sum(int(v) for v in shed_inv.values())

        market_obj = ctx.get("market")
        market_inv = {}
        if market_obj is not None:
            if isinstance(market_obj, dict):
                market_inv = {str(k): int(v) for k, v in market_obj.get("inventory", {}).items()}
            elif hasattr(market_obj, "inventory"):
                market_inv = {str(k): int(v) for k, v in market_obj.inventory.items()}

        try:
            from strategy.adaptive_acreage_planner import get_adaptive_acreage_planner
            planner = get_adaptive_acreage_planner()
            decision = planner.evaluate_expansion(
                current_day=day,
                current_hour=hour,
                current_admitted_tiles=set(self.state.admitted_sw_tiles),
                current_cash=current_cash,
                active_workers=active_workers,
                num_animals=num_animals,
                wheat_inventory=wheat_inventory,
                shed_inventory_units=shed_units,
                core_planted_tiles=core_planted,
                market_inventories=market_inv,
                max_acreage_cap=max_acreage_cap,
            )

            try:
                from config import get_sw_p3_transactional_reservations_enabled
                p3_enabled = bool(get_sw_p3_transactional_reservations_enabled())
            except Exception:
                try:
                    from agent.config import get_sw_p3_transactional_reservations_enabled
                    p3_enabled = bool(get_sw_p3_transactional_reservations_enabled())
                except Exception:
                    p3_enabled = False

            if p3_enabled and decision.approved:
                try:
                    from strategy.crop_cycle_reservation_manager import get_crop_cycle_reservation_manager
                except ImportError:
                    from agent.strategy.crop_cycle_reservation_manager import get_crop_cycle_reservation_manager
                res_mgr = get_crop_cycle_reservation_manager()
                trial = res_mgr.evaluate_complete_crop_cycle(
                    candidate_tiles=[(int(t[0]), int(t[1])) for t in decision.new_tiles],
                    candidate_crop=decision.selected_crop,
                    plant_day=day,
                    current_cash=current_cash,
                    active_workers=active_workers,
                    num_animals=num_animals,
                    wheat_inventory=wheat_inventory,
                    current_shed_occupancy=shed_units,
                    core_planted_tiles=core_planted,
                    market_inventories=market_inv,
                )
                if trial.feasible and trial.expected_whole_farm_delta > 0:
                    res_id = res_mgr.commit_reservation(trial)
                    for tile in decision.new_tiles:
                        tile_t = (int(tile[0]), int(tile[1]))
                        self.state.admitted_sw_tiles.add(tile_t)
                        self.state.admitted_sw_crop_targets[tile_t] = decision.selected_crop

                    self.state.max_admitted_acreage = len(self.state.admitted_sw_tiles)
                    self.state.last_expansion_day = day

                    event_rec = {
                        "day": day,
                        "hour": hour,
                        "from_acreage": decision.current_acreage,
                        "to_acreage": decision.target_acreage,
                        "crop": decision.selected_crop,
                        "new_tiles": [list(t) for t in decision.new_tiles],
                        "marginal_delta_fc": decision.marginal_delta_fc,
                        "seed_cost": decision.seed_cost,
                        "projected_revenue": decision.projected_revenue,
                        "cash_at_expansion": current_cash,
                        "workers": active_workers,
                        "reservation_id": res_id,
                    }
                    self.state.adaptive_expansion_history.append(event_rec)
                    logger.info(
                        f"[SWTrancheController] P3 RESERVATION COMMITTED on Day {day}: "
                        f"{decision.current_acreage} -> {decision.target_acreage} tiles "
                        f"with {decision.selected_crop} (Res: {res_id}, Margin: +${trial.expected_whole_farm_delta:.2f})"
                    )
                    return decision
                else:
                    # Binding rejection: no mutation of admitted tiles or crop targets
                    rej_rec = {
                        "day": day,
                        "hour": hour,
                        "current_acreage": decision.current_acreage,
                        "target_acreage": decision.target_acreage,
                        "reason": trial.rejection_reason,
                        "passed_certificates": trial.certificates,
                    }
                    self.state.expansion_rejections.append(rej_rec)
                    decision.approved = False
                    decision.rejection_reason = trial.rejection_reason
                    logger.info(
                        f"[SWTrancheController] P3 RESERVATION REJECTED on Day {day}: {trial.rejection_reason}"
                    )
                    return decision
            elif decision.approved:
                # Increment admitted tiles and crop targets (Baseline path when P3 is OFF)
                for tile in decision.new_tiles:
                    tile_t = (int(tile[0]), int(tile[1]))
                    self.state.admitted_sw_tiles.add(tile_t)
                    self.state.admitted_sw_crop_targets[tile_t] = decision.selected_crop

                self.state.max_admitted_acreage = len(self.state.admitted_sw_tiles)
                self.state.last_expansion_day = day

                event_rec = {
                    "day": day,
                    "hour": hour,
                    "from_acreage": decision.current_acreage,
                    "to_acreage": decision.target_acreage,
                    "crop": decision.selected_crop,
                    "new_tiles": [list(t) for t in decision.new_tiles],
                    "marginal_delta_fc": decision.marginal_delta_fc,
                    "seed_cost": decision.seed_cost,
                    "projected_revenue": decision.projected_revenue,
                    "cash_at_expansion": current_cash,
                    "workers": active_workers,
                }
                self.state.adaptive_expansion_history.append(event_rec)
                logger.info(
                    f"[SWTrancheController] ADAPTIVE EXPANSION APPROVED on Day {day}: "
                    f"{decision.current_acreage} -> {decision.target_acreage} tiles "
                    f"with {decision.selected_crop} (ΔFC=+${decision.marginal_delta_fc:.2f})"
                )
                return decision
            else:
                rej_rec = {
                    "day": day,
                    "hour": hour,
                    "current_acreage": decision.current_acreage,
                    "target_acreage": decision.target_acreage,
                    "reason": decision.rejection_reason,
                    "passed_certificates": decision.passed_certificates,
                }
                self.state.expansion_rejections.append(rej_rec)
                logger.debug(
                    f"[SWTrancheController] Adaptive expansion deferred on Day {day}: {decision.rejection_reason}"
                )
                return decision
        except Exception as exc:
            logger.warning(f"[SWTrancheController] maybe_evaluate_adaptive_expansion error: {exc}")
            return None

    def confirm_purchase(self, day: int, hour: int) -> None:
        """Authoritatively confirm SW purchase upon observing unlocked quadrant in engine."""
        self.state.sw_purchase_confirmed = True
        self.state.sw_unlock_observed = True
        self.state.sw_purchase_day = day
        self.state.sw_purchase_hour = hour
        self.state.sw_land_cost_paid = 2000.0

        # Update lifecycle telemetry
        self.state.lifecycle.sw_confirmed_step = day * 24 + hour
        self.state.lifecycle.sw_confirmed_day = day
        self.state.lifecycle.sw_confirmed_hour = hour
        self.state.lifecycle.sw_confirmed_cash_deduction = 2000.0

    def notify_market_orders_emitted(
        self,
        orders: List[Any],
        step: int,
        day: int,
        hour: int,
        farm_money: float,
        unlocked_quadrants: Set[str],
    ) -> None:
        """Inspect emitted market orders and track exact SW land order lifecycle."""
        if not self.is_treatment_active():
            return

        has_ne = "NE" in unlocked_quadrants
        has_sw = "SW" in unlocked_quadrants

        # Check for BUY_LAND order
        buy_land_idx = None
        for idx, o in enumerate(orders):
            if isinstance(o, (list, tuple)) and o and o[0] == "BUY_LAND":
                buy_land_idx = idx
                break

        if buy_land_idx is not None:
            # If NE is NOT unlocked, this BUY_LAND targets NE, NOT SW!
            if not has_ne:
                logger.debug(f"[SWTrancheController] BUY_LAND emitted at step {step} targets NE. Ignoring for SW telemetry.")
                return

            # If NE is unlocked and SW is NOT unlocked, this BUY_LAND targets SW!
            if has_ne and not has_sw:
                lc = self.state.lifecycle
                lc.purchase_attempt_steps.append(step)
                if lc.sw_order_emitted_step is None:
                    lc.sw_order_emitted_step = step
                    lc.sw_order_emitted_day = day
                    lc.sw_order_emitted_hour = hour
                else:
                    lc.purchase_retry_count += 1
                    lc.purchase_retry_steps.append(step)
                lc.sw_order_emitted_count += 1
                self.state.sw_land_order_emitted = True

                # Slot arbitration check: is it within top 10 market slots?
                if buy_land_idx < 10:
                    lc.sw_order_retained_step = step
                    lc.sw_order_retained_slot_index = buy_land_idx
                else:
                    lc.purchase_failed_events.append({
                        "step": step,
                        "day": day,
                        "hour": hour,
                        "reason": f"market_slot_truncation (slot {buy_land_idx} >= 10)",
                        "cash": farm_money,
                    })

    def observe_engine_step(
        self,
        obs: Dict[str, Any],
        seat: int,
        step: int,
        day: int,
        hour: int,
    ) -> None:
        """Authoritatively observe engine state transition."""
        if not self.is_treatment_active():
            return

        farm = obs.get("farms", [{}])[seat]
        unlocked = set(farm.get("unlocked_quadrants", ["NW"]))
        cur_cash = float(farm.get("money", 0.0))
        lc = self.state.lifecycle

        # Check engine confirmation of SW purchase
        if "SW" in unlocked:
            if lc.sw_confirmed_step is None:
                lc.sw_confirmed_step = step
                lc.sw_confirmed_day = day
                lc.sw_confirmed_hour = hour
                lc.exact_purchase_step = step
                lc.exact_purchase_day = day
                lc.exact_purchase_hour = hour
                lc.purchase_settled = True
                lc.cash_before_purchase = self.state.pre_purchase_cash
                lc.cash_after_purchase = cur_cash
                deduction = (self.state.pre_purchase_cash - cur_cash) if self.state.pre_purchase_cash > 0 else 2000.0
                lc.sw_confirmed_cash_deduction = float(deduction)
                self.confirm_purchase(day, hour)
        else:
            # If an order was retained in the previous step but SW is still not unlocked:
            if lc.sw_order_retained_step == step - 1:
                lc.purchase_failed_events.append({
                    "step": step - 1,
                    "day": (step - 1) // 24,
                    "hour": (step - 1) % 24,
                    "reason": "engine_rejected_or_insufficient_funds",
                    "cash": cur_cash,
                })
                if lc.sw_confirmed_step is None and self.state.sw_reservation_id and step >= 718:
                    try:
                        from strategy.crop_cycle_reservation_manager import get_crop_cycle_reservation_manager
                        get_crop_cycle_reservation_manager().cancel_reservation(self.state.sw_reservation_id, "engine_rejected")
                        self.state.sw_reservation_id = None
                    except Exception:
                        pass

        # Check physical tile planting in SW
        if "SW" in unlocked and lc.first_productive_plant_step is None:
            tiles = farm.get("tiles", [])
            for y, row in enumerate(tiles):
                if y < 5:
                    continue  # Only SW has y >= 5 and x < 5
                for x, cell in enumerate(row):
                    if x >= 5:
                        continue
                    if isinstance(cell, dict) and (cell.get("kind") == "PLANT" or "crop" in cell):
                        c_name = cell.get("crop")
                        p_day = cell.get("planted_day")
                        if c_name and p_day is not None:
                            lc.first_productive_plant_step = step
                            lc.first_productive_plant_day = day
                            lc.first_productive_plant_crop = c_name
                            lc.first_productive_plant_pos = (x, y)
                            break
                if lc.first_productive_plant_step is not None:
                    break

    def record_tile_harvest(self, pos: Tuple[int, int], crop: str, units: int) -> None:
        """Record tile harvest with coordinates."""
        self.state.provenance.record_harvest(pos, crop, units)

    def record_executed_sale(self, step: int, crop: str, units: int, unit_price: float) -> None:
        """Record executed market sale with unit price."""
        self.state.provenance.record_sale(step, crop, units, unit_price)

    def reconcile_conservation(self, final_obs: Dict[str, Any], seat: int) -> None:
        """Reconcile conservation of goods at end of match."""
        priv = final_obs.get("private", {})
        if not priv and "privates" in final_obs:
            priv = final_obs["privates"][seat]

        shed = priv.get("shed", {}) if isinstance(priv, dict) else {}
        invs = priv.get("inventories", []) if isinstance(priv, dict) else []

        for crop in ("STRAWBERRY", "MELON", "WHEAT", "CARROT", "TOMATO"):
            shed_qty = int(shed.get(crop, 0))
            worker_qty = sum(int(inv.get(crop, 0)) for inv in invs if isinstance(inv, dict))
            self.state.provenance.ending_shed_units[crop] = shed_qty
            self.state.provenance.ending_worker_units[crop] = worker_qty

            # Discarded units = total harvested - (sales + shed + worker)
            h_tot = self.state.provenance.core_harvested_units.get(crop, 0) + self.state.provenance.sw_harvested_units.get(crop, 0)
            s_tot = self.state.provenance.total_sales_units.get(crop, 0)
            diff = h_tot - (s_tot + shed_qty + worker_qty)
            self.state.provenance.discarded_overflow_units[crop] = max(0, diff)

    def notify_land_order_failed(self, reason: str) -> None:
        """Notify controller that emitted BUY_LAND order failed or was dropped."""
        self.state.sw_land_order_emitted = False
        self.state.purchase_failed_reason = str(reason)
        try:
            from strategy.crop_cycle_reservation_manager import get_crop_cycle_reservation_manager
            res_mgr = get_crop_cycle_reservation_manager()
            ids_to_cancel = list(self.state.sw_reservation_ids)
            if self.state.sw_reservation_id and self.state.sw_reservation_id not in ids_to_cancel:
                ids_to_cancel.append(self.state.sw_reservation_id)
            for res_id in ids_to_cancel:
                res_mgr.cancel_reservation(res_id, reason)
            self.state.sw_reservation_ids.clear()
            self.state.sw_reservation_id = None
        except Exception as exc:
            logger.debug(f"[SWTrancheController] Reservation cancellation note: {exc}")

    def record_seed_consumption(
        self,
        crop: str,
        qty: int = 1,
        from_inventory: bool = True,
        cash_spent: float = 0.0,
    ) -> None:
        """Record seed consumption distinguishing cash expenditure vs inventory consumption."""
        if from_inventory:
            cash_count = self.state.sw_seeds_bought_with_cash.get(crop, 0)
            if cash_count >= qty:
                self.state.sw_seeds_bought_with_cash[crop] -= qty
                return
            elif cash_count > 0:
                qty_from_cash = cash_count
                self.state.sw_seeds_bought_with_cash[crop] = 0
                qty -= qty_from_cash
            self.state.sw_seed_inventory_consumed[crop] = (
                self.state.sw_seed_inventory_consumed.get(crop, 0) + qty
            )
            unit_val = 100.0 if crop == "STRAWBERRY" else (80.0 if crop == "MELON" else 10.0)
            self.state.sw_seed_opportunity_cost += (unit_val * qty)
        if cash_spent > 0:
            self.state.sw_seed_cost_realized += float(cash_spent)
            self.state.sw_seeds_bought_with_cash[crop] = (
                self.state.sw_seeds_bought_with_cash.get(crop, 0) + qty
            )

    def filter_macro_plant_queue(
        self,
        plant_queue: List[Tuple[Tuple[int, int], str]],
        farm: Any,
    ) -> List[Tuple[Tuple[int, int], str]]:
        """Filter plant queue to enforce admitted tranche invariant.

        Any plant queue item targeting an SW tile not in admitted_sw_tiles is dropped.
        """
        if not self.is_treatment_active():
            return plant_queue

        filtered = []
        for pos, crop in plant_queue:
            pos_t = (int(pos[0]), int(pos[1]))
            is_sw = (pos_t[0] < 5 and pos_t[1] >= 5)
            if is_sw:
                if pos_t in self.state.admitted_sw_tiles:
                    # Enforce the specific target crop from the admitted portfolio
                    target_crop = self.state.admitted_sw_crop_targets.get(pos_t, crop)
                    filtered.append((pos_t, target_crop))
                else:
                    # Dropped to prevent unauthorized expansion
                    self.state.invariant_violations_attempted += 1
                    logger.debug(f"[SWTrancheController] Blocked unauthorized SW plant at {pos_t}")
            else:
                filtered.append((pos, crop))
        return filtered

    def filter_task_scheduler_tasks(self, tasks: List[Any], farm: Any) -> List[Any]:
        """Enforce tranche invariant on generated scheduler tasks."""
        if not self.is_treatment_active():
            return tasks

        filtered = []
        for task in tasks:
            op = getattr(task, "op", None) or (task.get("op") if isinstance(task, dict) else None)
            target = getattr(task, "target", None) or (task.get("target") if isinstance(task, dict) else None)
            if op == "PLANT" and target is not None:
                pos_t = (int(target[0]), int(target[1]))
                is_sw = (pos_t[0] < 5 and pos_t[1] >= 5)
                if is_sw and pos_t not in self.state.admitted_sw_tiles:
                    self.state.invariant_violations_attempted += 1
                    continue
            filtered.append(task)
        return filtered

    def record_turn(
        self,
        ctx: Dict[str, Any],
        asg: Any,
        market: List[Any],
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record per-turn execution observations, checkpoints, and safety telemetry."""
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)
        farm = ctx.get("farm")
        private = ctx.get("private")
        # Check authoritative engine confirmation of SW purchase
        if farm and hasattr(farm, "unlocked") and "SW" in farm.unlocked:
            if not self.state.sw_purchase_confirmed:
                self.confirm_purchase(day, hour)

        # Track post-purchase cash
        if self.state.sw_purchase_approved and self.state.sw_purchase_day == day and hour == 1:
            if farm:
                self.state.post_purchase_cash = float(farm.money)

        # Track feed wheat balance & safety
        if private and hasattr(private, "shed"):
            w_shed = int(private.shed.get("WHEAT", 0))
            if w_shed < self.state.min_feed_wheat_balance:
                self.state.min_feed_wheat_balance = w_shed
            shed_total = sum(int(v) for v in private.shed.values())
            if shed_total > self.state.peak_shed_usage:
                self.state.peak_shed_usage = shed_total

        # Track 9-stage land order lifecycle from market emissions
        if market and farm:
            unlocked_set = set(farm.unlocked if hasattr(farm, "unlocked") else ["NW"])
            self.notify_market_orders_emitted(
                orders=market,
                step=day * 24 + hour,
                day=day,
                hour=hour,
                farm_money=float(farm.money) if farm else 0.0,
                unlocked_quadrants=unlocked_set,
            )

        # Track executed sales of SW crops vs total farm sales & provenance
        if market:
            for order in market:
                if isinstance(order, (list, tuple)) and len(order) >= 3 and order[0] == "SELL":
                    prod = order[1]
                    qty = int(order[2])
                    m_obj = ctx.get("market")
                    px = float(getattr(m_obj, "prices", {}).get(prod, 0.0)) if m_obj else 0.0
                    self.record_executed_sale(day * 24 + hour, prod, qty, px)

                    admitted_crops = set(self.state.admitted_sw_crop_targets.values())
                    if prod in admitted_crops:
                        self.state.total_farm_portfolio_sales[prod] = (
                            self.state.total_farm_portfolio_sales.get(prod, 0) + qty
                        )
                        self.state.total_farm_portfolio_revenue += (px * qty)

                        # Bounded SW-origin attribution (max physical harvest: 16 units per crop type on 4 tiles)
                        max_sw_units = 16
                        curr_sw = self.state.sw_crops_sold.get(prod, 0)
                        rem_cap = max(0, max_sw_units - curr_sw)
                        sw_qty = min(qty, rem_cap) if self.state.sw_purchase_confirmed else 0
                        if sw_qty > 0:
                            self.state.sw_crops_sold[prod] = curr_sw + sw_qty
                            self.state.estimated_sw_origin_revenue += (px * sw_qty)
                        excess_qty = qty - sw_qty
                        if excess_qty > 0:
                            self.state.unattributable_mixed_origin_revenue += (px * excess_qty)
                        self.state.sw_revenue_realized = round(self.state.estimated_sw_origin_revenue, 2)

        # Track harvest and feed actions from assignment
        if asg and isinstance(asg, dict):
            actions = asg.get("actions", {})
            assignment = asg.get("assignment", {})
            for u_idx, act in actions.items():
                if isinstance(act, (list, tuple)) and act:
                    op = act[0]
                    if op == "FEED":
                        self.state.animals_fed_total += 1
                    elif op == "WATER":
                        self.state.core_watered_count += 1
                    elif op == "HARVEST":
                        self.state.core_harvest_count += 1
                        pos = None
                        if farm and hasattr(farm, "farmer"):
                            if u_idx == 0:
                                pos = tuple(farm.farmer)
                            elif hasattr(farm, "hands") and u_idx - 1 < len(farm.hands):
                                pos = tuple(farm.hands[u_idx - 1])
                        if pos and hasattr(farm, "tiles"):
                            try:
                                tile = farm.tiles[pos[1]][pos[0]] if pos[1] < len(farm.tiles) and pos[0] < len(farm.tiles[pos[1]]) else None
                                if tile:
                                    c_name = getattr(tile, "crop", None) or (tile.get("crop") if isinstance(tile, dict) else None)
                                    y_units = getattr(tile, "yield_units", 1) or (tile.get("yield_units", 1) if isinstance(tile, dict) else 1)
                                    if c_name:
                                        self.record_tile_harvest(pos, c_name, int(y_units))
                            except Exception:
                                pass
        # Track physical SW plantings from farm observation on Day rollover (hour 23)
        if farm and hasattr(farm, "iter_tiles") and hour == 23:
            for t in farm.iter_tiles():
                pos = (t.x, t.y) if hasattr(t, "x") else tuple(getattr(t, "pos", (0, 0)))
                if pos in self.state.admitted_sw_tiles:
                    crop = getattr(t, "crop", None)
                    p_day = getattr(t, "planted_day", None)
                    if crop and p_day == day:
                        self.state.sw_crops_planted[crop] = (
                            self.state.sw_crops_planted.get(crop, 0) + 1
                        )
                        self.record_seed_consumption(crop, qty=1, from_inventory=True)

        # Checkpoints relative to purchase day
        if self.state.sw_purchase_approved and self.state.sw_purchase_day is not None and hour == 23:
            p_day = self.state.sw_purchase_day
            d_offset = day - p_day
            offset_label = f"D+{d_offset}"
            if offset_label in ("D+0", "D+1", "D+2", "D+3", "D+5", "D+7") and farm:
                self.record_checkpoint(offset_label, farm)

    def record_checkpoint(self, label: str, farm: Any) -> None:
        """Capture authoritative SW utilization checkpoint."""
        sw_owned_tiles = 25  # standard 5x5 quadrant
        admitted_tiles = len(self.state.admitted_sw_tiles)
        planted_tiles = 0
        watered_tiles = 0
        harvestable_tiles = 0
        harvested_tiles = 0
        idle_tiles = 0

        for t in farm.iter_tiles():
            pos = (t.x, t.y) if hasattr(t, "x") else tuple(getattr(t, "pos", (0, 0)))
            is_sw = (pos[0] < 5 and pos[1] >= 5)
            if not is_sw:
                continue

            k = getattr(t, "kind", "")
            is_plant = getattr(t, "is_plant", False) or k == "PLANT"
            if is_plant:
                planted_tiles += 1
                if getattr(t, "watered_today", False):
                    watered_tiles += 1
                if getattr(t, "yield_units", 0) > 0:
                    harvestable_tiles += 1
            elif getattr(t, "is_empty", False) or k == "EMPTY":
                idle_tiles += 1

        whole_quad_util = round((planted_tiles / sw_owned_tiles) * 100.0, 1) if sw_owned_tiles > 0 else 0.0
        admitted_util = round((planted_tiles / admitted_tiles) * 100.0, 1) if admitted_tiles > 0 else 0.0

        self.state.checkpoints[label] = {
            "sw_owned_tiles": sw_owned_tiles,
            "sw_admitted_tiles": admitted_tiles,
            "sw_planted_tiles": planted_tiles,
            "sw_watered_tiles": watered_tiles,
            "sw_harvestable_tiles": harvestable_tiles,
            "sw_idle_tiles": idle_tiles,
            "whole_quadrant_utilization_pct": whole_quad_util,
            "admitted_tranche_utilization_pct": admitted_util,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Return complete structured summary of treatment execution."""
        return {
            "treatment_active": self.state.treatment_active,
            "sw_purchase_recommended": self.state.sw_purchase_recommended,
            "sw_purchase_approved": self.state.sw_purchase_approved,
            "sw_land_order_emitted": self.state.sw_land_order_emitted,
            "sw_purchase_confirmed": self.state.sw_purchase_confirmed,
            "sw_unlock_observed": self.state.sw_unlock_observed,
            "purchase_failed_reason": self.state.purchase_failed_reason,
            "sw_purchase_day": self.state.sw_purchase_day,
            "sw_purchase_hour": self.state.sw_purchase_hour,
            "selected_portfolio_name": self.state.selected_portfolio_name,
            "admitted_tiles_count": len(self.state.admitted_sw_tiles),
            "admitted_tiles": sorted(list(self.state.admitted_sw_tiles)),
            "admitted_crops": {f"{k[0]},{k[1]}": v for k, v in self.state.admitted_sw_crop_targets.items()},
            "predicted_delta_fc": round(self.state.predicted_delta_fc, 2),
            "pre_purchase_cash": round(self.state.pre_purchase_cash, 2),
            "post_purchase_cash": round(self.state.post_purchase_cash, 2),
            "worker_count_at_purchase": self.state.worker_count_at_purchase,
            "sw_land_cost_paid": self.state.sw_land_cost_paid,
            "sw_seed_cost_realized": round(self.state.sw_seed_cost_realized, 2),
            "sw_seed_inventory_consumed": dict(self.state.sw_seed_inventory_consumed),
            "sw_seed_opportunity_cost": round(self.state.sw_seed_opportunity_cost, 2),
            "sw_revenue_realized": round(self.state.sw_revenue_realized, 2),
            "sw_crops_sold": dict(self.state.sw_crops_sold),
            "total_farm_portfolio_sales": dict(self.state.total_farm_portfolio_sales),
            "total_farm_portfolio_revenue": round(self.state.total_farm_portfolio_revenue, 2),
            "estimated_sw_origin_revenue": round(self.state.estimated_sw_origin_revenue, 2),
            "unattributable_mixed_origin_revenue": round(self.state.unattributable_mixed_origin_revenue, 2),
            "checkpoints": dict(self.state.checkpoints),
            "rejection_reasons_by_day": {
                d: list(reasons) for d, reasons in self.state.rejection_reasons_by_day.items()
            },
            "primary_no_purchase_reason": self.state.primary_no_purchase_reason,
            "invariant_violations_attempted": self.state.invariant_violations_attempted,
            "sw_land_lifecycle": self.state.lifecycle.to_dict(),
            "crop_provenance": {
                crop: self.state.provenance.get_provenance_attribution(crop)
                for crop in ("STRAWBERRY", "MELON", "WHEAT", "CARROT", "TOMATO")
            },
            "core_safety": {
                "animals_fed_total": self.state.animals_fed_total,
                "core_watered_count": self.state.core_watered_count,
                "core_harvest_count": self.state.core_harvest_count,
                "min_feed_wheat_balance": self.state.min_feed_wheat_balance,
                "peak_shed_usage": self.state.peak_shed_usage,
            },
            "adaptive_acreage": {
                "max_admitted_acreage": self.state.max_admitted_acreage,
                "expansion_events_count": len(self.state.adaptive_expansion_history),
                "expansion_history": list(self.state.adaptive_expansion_history),
                "expansion_rejections": list(self.state.expansion_rejections),
            },
        }


# Module singleton instance
_SW_TRANCHE_CONTROLLER: Optional[SWTrancheController] = None


def get_sw_tranche_controller() -> SWTrancheController:
    """Return singleton SWTrancheController."""
    global _SW_TRANCHE_CONTROLLER
    if _SW_TRANCHE_CONTROLLER is None:
        _SW_TRANCHE_CONTROLLER = SWTrancheController()
    return _SW_TRANCHE_CONTROLLER


def reset_sw_tranche_controller() -> None:
    """Reset singleton SWTrancheController."""
    global _SW_TRANCHE_CONTROLLER
    if _SW_TRANCHE_CONTROLLER is not None:
        _SW_TRANCHE_CONTROLLER.reset()
    else:
        _SW_TRANCHE_CONTROLLER = SWTrancheController()
    try:
        from strategy.crop_cycle_reservation_manager import reset_crop_cycle_reservation_manager
        reset_crop_cycle_reservation_manager()
    except Exception:
        try:
            from agent.strategy.crop_cycle_reservation_manager import reset_crop_cycle_reservation_manager
            reset_crop_cycle_reservation_manager()
        except Exception:
            pass
