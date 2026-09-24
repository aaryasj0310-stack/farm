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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# All 25 SW coordinates on 10x10 board: x in [0, 4], y in [5, 9]
SW_COORDINATES: Set[Tuple[int, int]] = {
    (x, y) for x in range(5) for y in range(5, 10)
}
SW_PORT: Tuple[int, int] = (4, 5)


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

    # Economics & operations tracking
    sw_land_cost_paid: float = 0.0
    sw_seed_cost_realized: float = 0.0
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
                )
                return True, dec.selected_portfolio
            else:
                # Record rejection / delay reason
                reason = dec.disagreements_with_baseline[0].get("reason", dec.sw_recommendation_status) if dec.disagreements_with_baseline else dec.sw_recommendation_status
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

    def confirm_purchase(self, day: int, hour: int) -> None:
        """Authoritatively confirm SW purchase upon observing unlocked quadrant in engine."""
        self.state.sw_purchase_confirmed = True
        self.state.sw_unlock_observed = True
        self.state.sw_purchase_day = day
        self.state.sw_purchase_hour = hour
        self.state.sw_land_cost_paid = 2000.0

    def notify_land_order_failed(self, reason: str) -> None:
        """Notify controller that emitted BUY_LAND order failed or was dropped."""
        self.state.sw_land_order_emitted = False
        self.state.purchase_failed_reason = str(reason)

    def record_seed_consumption(
        self,
        crop: str,
        qty: int = 1,
        from_inventory: bool = True,
        cash_spent: float = 0.0,
    ) -> None:
        """Record seed consumption distinguishing cash expenditure vs inventory consumption."""
        if from_inventory:
            self.state.sw_seed_inventory_consumed[crop] = (
                self.state.sw_seed_inventory_consumed.get(crop, 0) + qty
            )
            unit_val = 100.0 if crop == "STRAWBERRY" else (80.0 if crop == "MELON" else 10.0)
            self.state.sw_seed_opportunity_cost += (unit_val * qty)
        if cash_spent > 0:
            self.state.sw_seed_cost_realized += float(cash_spent)

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

        # Track executed sales of SW crops vs total farm sales
        if market:
            for order in market:
                if isinstance(order, (list, tuple)) and len(order) >= 3 and order[0] == "SELL":
                    prod = order[1]
                    qty = int(order[2])
                    admitted_crops = set(self.state.admitted_sw_crop_targets.values())
                    if prod in admitted_crops:
                        self.state.total_farm_portfolio_sales[prod] = (
                            self.state.total_farm_portfolio_sales.get(prod, 0) + qty
                        )
                        m_obj = ctx.get("market")
                        px = float(getattr(m_obj, "prices", {}).get(prod, 0.0)) if m_obj else 0.0
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
            "admitted_crops": dict(self.state.admitted_sw_crop_targets),
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
            "core_safety": {
                "animals_fed_total": self.state.animals_fed_total,
                "core_watered_count": self.state.core_watered_count,
                "core_harvest_count": self.state.core_harvest_count,
                "min_feed_wheat_balance": self.state.min_feed_wheat_balance,
                "peak_shed_usage": self.state.peak_shed_usage,
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
