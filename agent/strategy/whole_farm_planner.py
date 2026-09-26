"""Whole-Farm Strategic Planner & Shadow-Mode Evaluation Harness.

Part of the SW-First Forward Architecture Redesign (Phase A).
Enforces strict decoupling:
- Live planner executes first, generating authoritative baseline action
- An immutable ShadowSnapshot is extracted
- WholeFarmPlanner runs in complete isolation
- Returns only ShadowResult (ShadowDecision, ShadowCertificate, ShadowDiagnostics)
- Never emits live engine actions or mutates live simulation context
- Implements event-driven replanning with execution latency telemetry (p50/p95/max)
"""
from __future__ import annotations

import copy
import sys
import time
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

try:
    from config import get_sw_forward_architecture_mode, CROPS, ANIMALS
    from strategy.farm_plan import FarmPlan, StrategicState, get_farm_plan, reset_farm_plan
    from strategy.resource_ledger import ResourceLedger, InflowConfidence
    from strategy.cohort_planner import CohortPlanner, CropCohort, OpportunityCostEvaluation
    from strategy.service_certificate import ServiceCertificate, CertificateResult, ServiceTask, CommitmentTier, serialize_candidate_certificate
    from state.observation_parser import needs_water_today, crop_produces_today, turns_until_decay
    from market.price_math import market_price, total_revenue_estimate
except ImportError:
    from config import get_sw_forward_architecture_mode, CROPS, ANIMALS
    from farm_plan import FarmPlan, StrategicState, get_farm_plan, reset_farm_plan
    from resource_ledger import ResourceLedger, InflowConfidence
    from cohort_planner import CohortPlanner, CropCohort, OpportunityCostEvaluation
    from service_certificate import ServiceCertificate, CertificateResult, ServiceTask, CommitmentTier, serialize_candidate_certificate
    from observation_parser import needs_water_today, crop_produces_today, turns_until_decay
    from price_math import market_price, total_revenue_estimate


@dataclass(frozen=True)
class ShadowSnapshot:
    """Immutable, deep-copied observation and diagnostic snapshot for shadow evaluation."""
    day: int
    hour: int
    step: int
    money: float
    unlocked_quadrants: Tuple[str, ...]
    unlocked_shops: Tuple[str, ...]
    shed_inventory: Tuple[Tuple[str, int], ...]
    carried_inventory_units: int
    market_prices: Tuple[Tuple[str, float], ...]
    market_inventories: Tuple[Tuple[str, int], ...]
    baseline_intents: Tuple[Tuple[str, Any], ...]
    active_worker_count: int
    tiles_summary: Tuple[Tuple[str, int], ...]
    animals_summary: Tuple[Tuple[str, int], ...] = ()

    @classmethod
    def from_live_state(
        cls,
        ctx: Dict[str, Any],
        mem: Dict[str, Any],
        plan: Any,
        asg: Any,
        market: List[Any],
    ) -> ShadowSnapshot:
        """Create a completely frozen, immutable snapshot from live turn state."""
        farm = ctx.get("farm")
        private = ctx.get("private")
        town = ctx.get("town")

        money = float(getattr(farm, "money", 0.0)) if farm else 0.0
        unlocked = tuple(str(q) for q in getattr(farm, "unlocked", [])) if farm else ()
        unlocked_shops = tuple(getattr(town, "unlocked_shops", [])) if town else ()

        shed_dict = getattr(private, "shed", {}) if private else {}
        shed_tuple = tuple(sorted((str(k), int(v)) for k, v in shed_dict.items()))

        carried = 0
        for inv in getattr(private, "inventories", []) if private else []:
            if isinstance(inv, dict):
                carried += sum(int(v) for v in inv.values())

        m_obj = ctx.get("market")
        m_prices = tuple(sorted((str(k), float(v)) for k, v in getattr(m_obj, "prices", {}).items())) if m_obj else ()
        m_inv = tuple(sorted((str(k), int(v)) for k, v in getattr(m_obj, "inventory", {}).items())) if m_obj else ()

        intents_dict = getattr(plan, "intents", {}) if plan else {}
        intents_tuple = tuple(sorted((str(k), copy.deepcopy(v)) for k, v in intents_dict.items() if k != "execution_snapshot"))

        workers = 1 + (len(getattr(farm, "hands", [])) if farm else 0)

        # Count tiles by kind for light representation
        tile_counts: Dict[str, int] = {}
        # Count animals accurately by observed species/state
        animal_counts: Dict[str, int] = {}
        if farm:
            for t in farm.iter_tiles():
                k = getattr(t, "kind", "EMPTY")
                tile_counts[k] = tile_counts.get(k, 0) + 1
                is_anim = getattr(t, "is_animal", False) or (getattr(t, "animal", None) is not None)
                if is_anim:
                    sp = getattr(t, "animal", None)
                    if not sp or sp is True or sp not in ANIMALS:
                        if k in ANIMALS:
                            sp = k
                        elif k == "COOP":
                            sp = "CHICKEN"
                        else:
                            sp = "COW"
                    animal_counts[sp] = animal_counts.get(sp, 0) + 1
        tile_counts_tuple = tuple(sorted(tile_counts.items()))
        animals_tuple = tuple(sorted(animal_counts.items()))

        return cls(
            day=ctx.get("day", 0),
            hour=ctx.get("hour", 0),
            step=ctx.get("step", 0),
            money=money,
            unlocked_quadrants=unlocked,
            unlocked_shops=unlocked_shops,
            shed_inventory=shed_tuple,
            carried_inventory_units=carried,
            market_prices=m_prices,
            market_inventories=m_inv,
            baseline_intents=intents_tuple,
            active_worker_count=workers,
            tiles_summary=tile_counts_tuple,
            animals_summary=animals_tuple,
        )


@dataclass
class ShadowDecision:
    """Shadow-mode planning decisions."""
    strategic_state: str
    target_sw_day: int
    sw_purchase_recommended: bool
    proposed_crop_cohorts: List[str] = field(default_factory=list)
    proposed_livestock_cohorts: List[str] = field(default_factory=list)
    proposed_hires: int = 0
    disagreements_with_baseline: List[Dict[str, Any]] = field(default_factory=list)
    selected_portfolio: Optional[Dict[str, Any]] = None
    market_valuation_discrepancies: List[Dict[str, Any]] = field(default_factory=list)
    # Phase A-R5 enriched telemetry
    sw_recommendation_status: str = "REJECT"  # "PURCHASE", "DELAY", "DOWNSIZE", "REJECT"
    baseline_sw_purchase: bool = False
    core_only_cert_feasible: bool = True
    combined_cert_feasible: bool = True
    lifecycle_workload_feasible: bool = True
    binding_resource: str = "NONE"
    binding_deadline: Optional[int] = None
    portfolio_delta_fc: float = 0.0
    sw_land_cost: float = 2000.0
    sw_seed_cost: float = 0.0
    sw_incremental_labor_cost: float = 0.0
    sw_gross_revenue: float = 0.0
    core_cannibalization_loss: float = 0.0
    displaced_core_value: float = 0.0
    feed_opportunity_cost: float = 0.0
    storage_loss_penalty: float = 0.0
    projected_terminal_cash_without: float = 0.0
    projected_terminal_cash_with: float = 0.0
    candidates_evaluated_count: int = 0
    candidates_admitted_count: int = 0
    candidates_delayed_count: int = 0
    candidates_downsized_count: int = 0
    candidates_rejected_count: int = 0
    verified_service_feasible: bool = True
    economic_uncertainty_flags: List[str] = field(default_factory=list)
    # Phase B0 counterfactual ownership state
    virtual_sw_owned: bool = False
    virtual_sw_purchase_day: Optional[int] = None
    virtual_cash: float = 0.0
    actual_sw_unlocked: bool = False
    selected_candidate_certificate: Optional[Dict[str, Any]] = None


@dataclass
class ShadowDiagnostics:
    """Telemetry and operational metrics for shadow evaluation."""
    latency_ms: float
    event_replan_triggered: bool
    resource_slack: int
    feed_is_safe: bool
    cash_projected_available: float
    binding_resource: str
    repair_options_count: int
    storage_is_safe: bool = True
    lifecycle_feasible: bool = True
    full_lifecycle_peak_shed: int = 0
    full_lifecycle_peak_daily_actions: int = 0


@dataclass
class ShadowResult:
    """Complete, self-contained output of shadow planning turn."""
    decision: ShadowDecision
    certificate: CertificateResult
    diagnostics: ShadowDiagnostics


class WholeFarmPlanner:
    """Strategic orchestrator evaluating whole-farm forward trajectories."""

    def __init__(self, farm_plan: Optional[FarmPlan] = None) -> None:
        self.farm_plan: FarmPlan = farm_plan if farm_plan is not None else FarmPlan()
        self.ledger: ResourceLedger = ResourceLedger()
        self.cohort_planner: CohortPlanner = CohortPlanner()
        self.certificate_evaluator: ServiceCertificate = ServiceCertificate()

        # Telemetry history
        self.latencies_ms: List[float] = []
        self.latest_result: Optional[ShadowResult] = None
        self.last_replan_day: int = -1

        # Phase B0 counterfactual state tracking
        self.virtual_sw_owned: bool = False
        self.virtual_sw_purchase_day: Optional[int] = None
        self.virtual_sw_purchase_tranche: Optional[str] = None
        self.virtual_sw_purchase_tiles: int = 0
        self.virtual_land_cost_paid: float = 0.0

    def reset(self) -> None:
        """Reset internal planner state for a new game session."""
        self.farm_plan = FarmPlan()
        self.ledger = ResourceLedger()
        self.cohort_planner = CohortPlanner()
        self.certificate_evaluator = ServiceCertificate()
        self.latencies_ms = []
        self.latest_result = None
        self.last_replan_day = -1
        self.virtual_sw_owned = False
        self.virtual_sw_purchase_day = None
        self.virtual_sw_purchase_tranche = None
        self.virtual_sw_purchase_tiles = 0
        self.virtual_land_cost_paid = 0.0

    def _append_daily_animal_tasks(
        self,
        tasks: List[ServiceTask],
        snapshot: ShadowSnapshot,
        raw_ctx: Optional[Dict[str, Any]],
        eval_day: int,
    ) -> None:
        """Schedule daily animal feeding tasks grounded in actual observed animal locations/species."""
        animal_tiles: List[Tuple[int, int]] = []
        if raw_ctx and "farm" in raw_ctx:
            for t in raw_ctx["farm"].iter_tiles():
                is_anim = getattr(t, "is_animal", False) or (getattr(t, "animal", None) is not None) or getattr(t, "kind", None) in ANIMALS
                if is_anim:
                    animal_tiles.append((t.x, t.y))

        def _calc_feed_h(idx_val: int) -> int:
            if eval_day == snapshot.day:
                if snapshot.hour < 4:
                    return max(snapshot.hour + 1, min(23, 4 + (idx_val % 6)))
                return max(snapshot.hour + 1, min(23, snapshot.hour + 1 + (idx_val % 4)))
            return 4 + (idx_val % 6)

        if animal_tiles:
            for idx, (ax, ay) in enumerate(animal_tiles):
                feed_h = _calc_feed_h(idx)
                tasks.append(
                    ServiceTask(
                        task_id=f"feed_animal_{ax}_{ay}_d{eval_day}",
                        op="FEED",
                        pos=(ax, ay),
                        region="NW" if ay < 5 else "SW",
                        day=eval_day,
                        hour_deadline=feed_h,
                        tier=CommitmentTier.HARD,
                        estimated_duration_actions=1,
                    )
                )
        elif snapshot.animals_summary:
            idx = 0
            for sp, count in snapshot.animals_summary:
                for _ in range(count):
                    feed_h = _calc_feed_h(idx)
                    tasks.append(
                        ServiceTask(
                            task_id=f"feed_animal_{sp}_{idx}_d{eval_day}",
                            op="FEED",
                            pos=(2, 2),
                            region="NW",
                            day=eval_day,
                            hour_deadline=feed_h,
                            tier=CommitmentTier.HARD,
                            estimated_duration_actions=1,
                        )
                    )
                    idx += 1
        else:
            idx = 0
            for sp, count in snapshot.tiles_summary:
                if sp in ANIMALS:
                    for _ in range(count):
                        feed_h = _calc_feed_h(idx)
                        tasks.append(
                            ServiceTask(
                                task_id=f"feed_animal_{sp}_{idx}_d{eval_day}",
                                op="FEED",
                                pos=(2, 2),
                                region="NW",
                                day=eval_day,
                                hour_deadline=feed_h,
                                tier=CommitmentTier.HARD,
                                estimated_duration_actions=1,
                            )
                        )
                        idx += 1

    def _build_core_tasks(
        self,
        snapshot: ShadowSnapshot,
        raw_ctx: Optional[Dict[str, Any]] = None,
        horizon_days: int = 3,
    ) -> List[ServiceTask]:
        """Build observation-grounded core NW/NE workload tasks over the rolling horizon."""
        simulated_tasks: List[ServiceTask] = []
        plan = self.farm_plan

        for d_offset in range(horizon_days):
            eval_day = snapshot.day + d_offset
            if eval_day >= 30:
                break

            # 1. Animal feeding obligations
            if d_offset == 0:
                # Outstanding animal feeding liabilities for today from ledger
                day_liabs = [l for l in self.ledger.feed_liabilities if l.day == eval_day]
                if day_liabs:
                    for idx, liab in enumerate(day_liabs):
                        h_dl = max(snapshot.hour + 1, min(liab.hour_deadline, 4 + (idx % 6))) if snapshot.hour < 4 else max(snapshot.hour + 1, min(liab.hour_deadline, snapshot.hour + 1 + (idx % 4)))
                        simulated_tasks.append(
                            ServiceTask(
                                task_id=f"feed_animal_{liab.animal_pos[0]}_{liab.animal_pos[1]}_d{eval_day}",
                                op="FEED",
                                pos=liab.animal_pos,
                                region="NW" if liab.animal_pos[1] < 5 else "SW",
                                day=eval_day,
                                hour_deadline=min(23, h_dl),
                                tier=CommitmentTier.HARD,
                                estimated_duration_actions=1,
                            )
                        )
                else:
                    self._append_daily_animal_tasks(simulated_tasks, snapshot, raw_ctx, eval_day)
            else:
                self._append_daily_animal_tasks(simulated_tasks, snapshot, raw_ctx, eval_day)

            # 2. Existing NW/NE in-ground wheat harvests from ledger
            for idx, h in enumerate(self.ledger.in_ground_wheat):
                if h.earliest_harvest_day == eval_day:
                    h_dl = max(snapshot.hour + 1, min(23, 6 + (idx % 8))) if eval_day == snapshot.day else (6 + (idx % 8))
                    simulated_tasks.append(
                        ServiceTask(
                            task_id=f"harvest_wheat_{h.tile_pos[0]}_{h.tile_pos[1]}_d{eval_day}",
                            op="HARVEST",
                            pos=h.tile_pos,
                            region="NW",
                            day=eval_day,
                            hour_deadline=h_dl,
                            tier=CommitmentTier.HARD,
                            estimated_duration_actions=1,
                        )
                    )

            # 3. Grounded core crop maintenance with stateful forward lifecycle projection
            if raw_ctx and "farm" in raw_ctx:
                farm_obj = raw_ctx["farm"]
                for t in farm_obj.iter_tiles():
                    # Core tiles only (exclude SW region tiles x < 5, y >= 5)
                    is_sw_tile = (t.x < 5 and t.y >= 5)
                    if is_sw_tile:
                        continue
                    if getattr(t, "is_plant", False):
                        crop_name = getattr(t, "crop", None)
                        if not crop_name:
                            continue
                        cd = CROPS.get(crop_name, {})
                        planted_day = getattr(t, "planted_day", snapshot.day)
                        is_ongoing = cd.get("ongoing", False)
                        max_m = cd.get("max_yield_day", 4)
                        harvest_day = planted_day + max_m

                        # --- WATERING FORECAST ---
                        needs_water = False
                        is_survival = False

                        if d_offset == 0:
                            # Day 0 (Today): inspect current observation
                            watered_today = getattr(t, "watered_today", False)
                            if not watered_today:
                                consecutive_unwatered = int(getattr(t, "consecutive_unwatered", 0) or 0)
                                if consecutive_unwatered >= 1 or planted_day == eval_day:
                                    needs_water = True
                                    is_survival = True
                                else:
                                    if is_ongoing:
                                        fert_until = getattr(t, "fertilized_until_day", -1)
                                        if crop_produces_today(t, eval_day) and fert_until >= eval_day:
                                            needs_water = True
                                        else:
                                            needs_water = ((t.x + t.y + eval_day) % 2 == 0)
                                    else:
                                        age = eval_day - planted_day
                                        if eval_day < harvest_day:
                                            w_start = (max_m + 1) // 2
                                            if w_start <= age:
                                                needs_water = True
                                            else:
                                                needs_water = ((t.x + t.y + eval_day) % 2 == 0)
                                        else:
                                            needs_water = False
                        else:
                            # Future days: project lifecycle forward
                            if is_ongoing:
                                days_since_first = eval_day - planted_day - cd.get("first_yield_day", 3)
                                interval = cd.get("interval", 2)
                                max_yield = cd.get("max_yield", 6)
                                produces = (days_since_first >= 0 and days_since_first % interval == 0 and (days_since_first // interval + 1) <= max_yield)
                                fert_until = getattr(t, "fertilized_until_day", -1)
                                if produces and fert_until >= eval_day:
                                    needs_water = True
                                else:
                                    needs_water = ((t.x + t.y + eval_day) % 2 == 0)
                            else:
                                age = eval_day - planted_day
                                if eval_day < harvest_day:
                                    w_start = (max_m + 1) // 2
                                    if w_start <= age:
                                        needs_water = True
                                    else:
                                        needs_water = ((t.x + t.y + eval_day) % 2 == 0)
                                else:
                                    needs_water = False

                        if needs_water:
                            simulated_tasks.append(
                                ServiceTask(
                                    task_id=f"core_water_{t.x}_{t.y}_d{eval_day}",
                                    op="WATER",
                                    pos=(t.x, t.y),
                                    region="NW" if t.x < 5 else "NE",
                                    day=eval_day,
                                    hour_deadline=23 if is_survival else (18 + ((t.x + t.y) % 5)),
                                    tier=CommitmentTier.HARD if is_survival else CommitmentTier.STRATEGIC,
                                    estimated_duration_actions=1,
                                )
                            )

                        # --- HARVEST FORECAST ---
                        if is_ongoing:
                            days_since_first = eval_day - planted_day - cd.get("first_yield_day", 3)
                            interval = cd.get("interval", 2)
                            max_yield = cd.get("max_yield", 6)
                            produces_on_day = (days_since_first >= 0 and days_since_first % interval == 0 and (days_since_first // interval + 1) <= max_yield)
                            if produces_on_day or (d_offset == 0 and getattr(t, "yield_units", 0) > 0):
                                simulated_tasks.append(
                                    ServiceTask(
                                        task_id=f"core_harvest_{t.x}_{t.y}_d{eval_day}",
                                        op="HARVEST",
                                        pos=(t.x, t.y),
                                        region="NW" if t.x < 5 else "NE",
                                        day=eval_day,
                                        hour_deadline=18 + ((t.x + t.y) % 5),
                                        tier=CommitmentTier.HARD,
                                        estimated_duration_actions=1,
                                    )
                                )
                        else:
                            # One-time crop: harvested only ONCE upon reaching maturity day
                            age = eval_day - planted_day
                            if (d_offset == 0 and age >= max_m) or (eval_day == harvest_day):
                                in_ledger = any(h.tile_pos == (t.x, t.y) and h.earliest_harvest_day == eval_day for h in self.ledger.in_ground_wheat)
                                if not in_ledger:
                                    simulated_tasks.append(
                                        ServiceTask(
                                            task_id=f"core_harvest_{t.x}_{t.y}_d{eval_day}",
                                            op="HARVEST",
                                            pos=(t.x, t.y),
                                            region="NW" if t.x < 5 else "NE",
                                            day=eval_day,
                                            hour_deadline=18 + ((t.x + t.y) % 5),
                                            tier=CommitmentTier.HARD,
                                            estimated_duration_actions=1,
                                        )
                                    )
            else:
                # Fallback from snapshot tile summary
                planted_count = sum(cnt for k, cnt in snapshot.tiles_summary if k in ("CARROT", "MELON", "WHEAT", "STRAWBERRY", "TOMATO", "PLANT"))
                if planted_count > 0:
                    simulated_tasks.append(
                        ServiceTask(
                            task_id=f"core_crop_water_summary_d{eval_day}",
                            op="WATER",
                            pos=(3, 3),
                            region="NW",
                            day=eval_day,
                            hour_deadline=18,
                            tier=CommitmentTier.HARD,
                            estimated_duration_actions=min(12, max(2, planted_count // 3)),
                        )
                    )

            if eval_day == snapshot.day and plan and getattr(plan, "plant_queue", None):
                for pq_idx, pq_item in enumerate(plan.plant_queue):
                    pq_pos = getattr(pq_item, "pos", (1, 1))
                    if not (pq_pos[0] < 5 and pq_pos[1] >= 5):
                        h_dl = max(snapshot.hour + 1, min(23, 12 + (pq_idx % 6)))
                        simulated_tasks.append(
                            ServiceTask(
                                task_id=f"core_plant_queue_{pq_idx}_d{eval_day}",
                                op="PLANT",
                                pos=pq_pos,
                                region="NW" if pq_pos[0] < 5 else "NE",
                                day=eval_day,
                                hour_deadline=h_dl,
                                tier=CommitmentTier.HARD,
                                estimated_duration_actions=1,
                            )
                        )

        return simulated_tasks

    def _build_candidate_sw_tasks(
        self,
        portfolio: Dict[str, Any],
        snapshot: ShadowSnapshot,
        horizon_days: int = 3,
    ) -> List[ServiceTask]:
        """Generate prospective SW service tasks (plant, water, harvest) for candidate portfolio."""
        sw_tasks: List[ServiceTask] = []
        for d_offset in range(horizon_days):
            eval_day = snapshot.day + d_offset
            if eval_day >= 30:
                break

            t_idx = 0
            for crop_name, n_units, tiles in portfolio.get("allocations", []):
                cd = CROPS.get(crop_name, {})
                if d_offset == 0:
                    # Planting day requires PLANT (afternoon) + WATER (evening)
                    for t_pos in tiles:
                        plant_h = 12 + (t_idx % 6)
                        water_h = 18 + (t_idx % 5)
                        t_idx += 1
                        sw_tasks.append(
                            ServiceTask(
                                task_id=f"sw_plant_{crop_name.lower()}_{t_pos[0]}_{t_pos[1]}_d{eval_day}",
                                op="PLANT",
                                pos=t_pos,
                                region="SW",
                                day=eval_day,
                                hour_deadline=plant_h,
                                tier=CommitmentTier.STRATEGIC,
                                estimated_duration_actions=1,
                                cohort_id=f"sw_{crop_name.lower()}",
                            )
                        )
                        sw_tasks.append(
                            ServiceTask(
                                task_id=f"sw_water_{crop_name.lower()}_{t_pos[0]}_{t_pos[1]}_d{eval_day}",
                                op="WATER",
                                pos=t_pos,
                                region="SW",
                                day=eval_day,
                                hour_deadline=water_h,
                                tier=CommitmentTier.STRATEGIC,
                                estimated_duration_actions=1,
                                cohort_id=f"sw_{crop_name.lower()}",
                            )
                        )
                else:
                    for t_pos in tiles:
                        work_h = 14 + (t_idx % 7)
                        t_idx += 1
                        if cd.get("ongoing", False):
                            # Ongoing crop: alternate day watering
                            if (t_pos[0] + t_pos[1] + eval_day) % 2 == 0:
                                sw_tasks.append(
                                    ServiceTask(
                                        task_id=f"sw_water_{crop_name.lower()}_{t_pos[0]}_{t_pos[1]}_d{eval_day}",
                                        op="WATER",
                                        pos=t_pos,
                                        region="SW",
                                        day=eval_day,
                                        hour_deadline=work_h,
                                        tier=CommitmentTier.STRATEGIC,
                                        estimated_duration_actions=1,
                                        cohort_id=f"sw_{crop_name.lower()}",
                                    )
                                )
                        else:
                            first_yield = cd.get("first_yield_day", 2)
                            if d_offset >= first_yield:
                                sw_tasks.append(
                                    ServiceTask(
                                        task_id=f"sw_harvest_{crop_name.lower()}_{t_pos[0]}_{t_pos[1]}_d{eval_day}",
                                        op="HARVEST",
                                        pos=t_pos,
                                        region="SW",
                                        day=eval_day,
                                        hour_deadline=work_h,
                                        tier=CommitmentTier.HARD,
                                        estimated_duration_actions=1,
                                        cohort_id=f"sw_{crop_name.lower()}",
                                    )
                                )
                            else:
                                sw_tasks.append(
                                    ServiceTask(
                                        task_id=f"sw_water_{crop_name.lower()}_{t_pos[0]}_{t_pos[1]}_d{eval_day}",
                                        op="WATER",
                                        pos=t_pos,
                                        region="SW",
                                        day=eval_day,
                                        hour_deadline=work_h,
                                        tier=CommitmentTier.STRATEGIC,
                                        estimated_duration_actions=1,
                                        cohort_id=f"sw_{crop_name.lower()}",
                                    )
                                )
        return sw_tasks

    def _project_feasible_sales(
        self,
        snapshot: ShadowSnapshot,
        core_crop_harvests: Dict[str, int],
        portfolio: Dict[str, Any],
        raw_ctx: Optional[Dict[str, Any]] = None,
        horizon_days: Optional[int] = None,
    ) -> Dict[int, int]:
        """Project feasible market sales that can realistically clear shed headroom.

        Constraints enforced:
        1. Stock source: Only goods currently in the shed (or already deposited) can be sold.
           Backpack items and unharvested future crops cannot be sold from the shed in advance.
        2. Feed preservation: Wheat reserved for animal feeding (num_animals * days_left) is protected and never sold.
        3. Market availability: Market must have positive prices and accessible market.
           If market_prices is explicitly provided and empty, or prices are non-positive, no sales can occur.
        4. Transport & throughput limits: Sales bounded by worker transport (up to 20 units/day)
           and market daily order limits (10 units/turn).
        Returns a dict mapping day -> units sold and removed from shed.
        """
        start_day = snapshot.day
        end_day = 30 if horizon_days is None else min(30, start_day + horizon_days)
        m_prices = dict(snapshot.market_prices)

        # Verify market price availability
        if snapshot.market_prices:
            has_positive_price = any(p > 0 for _, p in snapshot.market_prices)
            if not has_positive_price:
                return {}
        else:
            market_obj = raw_ctx.get("market") if raw_ctx else None
            if market_obj and hasattr(market_obj, "prices") and market_obj.prices:
                m_prices = {str(k): float(v) for k, v in market_obj.prices.items()}
                if not any(p > 0 for p in m_prices.values()):
                    return {}
            else:
                return {}

        # 1. Livestock feed reservation
        num_animals = 0
        if raw_ctx and "farm" in raw_ctx:
            for t in raw_ctx["farm"].iter_tiles():
                if getattr(t, "is_animal", False) or (getattr(t, "animal", None) is not None) or getattr(t, "kind", None) in ANIMALS:
                    num_animals += 1
        elif snapshot.animals_summary:
            num_animals = sum(cnt for _, cnt in snapshot.animals_summary)
        else:
            num_animals = sum(cnt for k, cnt in snapshot.tiles_summary if k in ANIMALS)

        days_left = max(0, 30 - start_day)
        protected_feed = num_animals * days_left

        # 2. Count existing sellable goods in shed
        sellable_shed_stock = 0
        for item, count in snapshot.shed_inventory:
            if count <= 0:
                continue
            if m_prices.get(item, 0.0) <= 0.0:
                continue
            if item == "WHEAT":
                avail_wheat = max(0, count - protected_feed)
                sellable_shed_stock += avail_wheat
            else:
                sellable_shed_stock += count

        if sellable_shed_stock <= 0:
            return {}

        # 3. Schedule sales across days up to end_day, subject to daily transport throughput
        active_workers = max(1, snapshot.active_worker_count)
        daily_sale_limit = min(20, active_workers * 10)

        planned_sales: Dict[int, int] = {}
        rem_stock = sellable_shed_stock

        for d in range(start_day, end_day):
            if rem_stock <= 0:
                break
            can_sell = min(rem_stock, daily_sale_limit)
            planned_sales[d] = can_sell
            rem_stock -= can_sell

        return planned_sales

    def _evaluate_candidate_lifecycle(
        self,
        portfolio: Dict[str, Any],
        snapshot: ShadowSnapshot,
        horizon_days: Optional[int] = None,
        raw_ctx: Optional[Dict[str, Any]] = None,
        planned_sales: Optional[Dict[int, int]] = None,
    ) -> Tuple[bool, int, int, Optional[str]]:
        """Validate downstream actions (PLANT, WATER, HARVEST, TRANSPORT, PLACE) through Day 29.

        Tracks labor constraints (daily worker hours envelope = active_workers * 24)
        and storage capacity envelope (shed inventory <= 100 units).
        Combines core obligations (livestock daily feeding + core crop watering and harvests)
        and proposed SW tasks.
        Non-repeated harvests for one-time crops.
        Defensible harvest quantities: WHEAT (6), MELON (2), CARROT (4), STRAWBERRY (1), TOMATO (1).
        Storage as a flow with feasible market sales clearing headroom.
        Returns (feasible, peak_shed, peak_daily_actions, failure_reason).
        """
        start_day = snapshot.day
        end_day = 30 if horizon_days is None else min(30, start_day + horizon_days)
        active_workers = max(1, snapshot.active_worker_count)
        daily_action_capacity = active_workers * 24

        current_shed_count = sum(cnt for _, cnt in snapshot.shed_inventory)
        peak_shed = current_shed_count
        peak_daily_actions = 0

        daily_actions: Dict[int, int] = {d: 0 for d in range(start_day, end_day)}
        daily_commercial_additions: Dict[int, int] = {d: 0 for d in range(start_day, end_day)}
        daily_wheat_additions: Dict[int, int] = {d: 0 for d in range(start_day, end_day)}

        # 1. Core livestock feed obligations
        num_animals = 0
        if raw_ctx and "farm" in raw_ctx:
            for t in raw_ctx["farm"].iter_tiles():
                if getattr(t, "is_animal", False) or (getattr(t, "animal", None) is not None) or getattr(t, "kind", None) in ANIMALS:
                    num_animals += 1
        elif snapshot.animals_summary:
            num_animals = sum(cnt for _, cnt in snapshot.animals_summary)
        else:
            num_animals = sum(cnt for k, cnt in snapshot.tiles_summary if k in ANIMALS)

        for d in range(start_day, end_day):
            # Feeding action + feed transport/fetch overhead = 2 actions/day/animal
            daily_actions[d] += (num_animals * 2)

        # 2. Core crop obligations
        if raw_ctx and "farm" in raw_ctx:
            farm_obj = raw_ctx["farm"]
            for t in farm_obj.iter_tiles():
                is_sw_tile = (t.x < 5 and t.y >= 5)
                if is_sw_tile or not getattr(t, "is_plant", False):
                    continue
                crop_name = getattr(t, "crop", None)
                if not crop_name:
                    continue
                cd = CROPS.get(crop_name, {})
                planted_day = getattr(t, "planted_day", snapshot.day)
                is_ongoing = cd.get("ongoing", False)
                first_yield = cd.get("first_yield_day", 2)
                interval = cd.get("interval", 2)
                max_yield_count = cd.get("max_yield", 6)
                max_yield_day = cd.get("max_yield_day", 4)

                yield_per_harvest = 1
                if crop_name == "WHEAT":
                    yield_per_harvest = 6
                elif crop_name == "CARROT":
                    yield_per_harvest = 4
                elif crop_name == "MELON":
                    yield_per_harvest = 2

                if is_ongoing:
                    for d in range(start_day, end_day):
                        age = d - planted_day
                        days_since_first = age - first_yield
                        if days_since_first >= 0 and (days_since_first % interval == 0) and ((days_since_first // interval) < max_yield_count):
                            daily_actions[d] += 2
                            if crop_name == "WHEAT":
                                daily_wheat_additions[d] += yield_per_harvest
                            else:
                                daily_commercial_additions[d] += yield_per_harvest
                        else:
                            if (t.x + t.y + d) % 2 == 0:
                                daily_actions[d] += 1
                else:
                    harvest_day = planted_day + max_yield_day
                    if start_day <= harvest_day < end_day:
                        daily_actions[harvest_day] += 2
                        if crop_name == "WHEAT":
                            daily_wheat_additions[harvest_day] += yield_per_harvest
                        else:
                            daily_commercial_additions[harvest_day] += yield_per_harvest
                    w_start = (max_yield_day + 1) // 2
                    for d in range(start_day, min(end_day, harvest_day)):
                        age = d - planted_day
                        if age >= w_start:
                            daily_actions[d] += 1
        else:
            planted_count = sum(cnt for k, cnt in snapshot.tiles_summary if k in ("CARROT", "MELON", "WHEAT", "STRAWBERRY", "TOMATO", "PLANT"))
            if planted_count > 0:
                base_core_actions = min(12, max(2, planted_count // 3))
                for d in range(start_day, end_day):
                    daily_actions[d] += base_core_actions

        # 3. Prospective SW Candidate obligations
        for crop_name, n_units, tiles in portfolio.get("allocations", []):
            cd = CROPS.get(crop_name, {})
            is_ongoing = cd.get("ongoing", False)
            first_yield = cd.get("first_yield_day", 2)
            interval = cd.get("interval", 2)
            max_yield_count = cd.get("max_yield", 6) if is_ongoing else 1
            max_yield_day = cd.get("max_yield_day", 4)
            n_tiles = len(tiles)

            yield_per_tile = 1
            if crop_name == "WHEAT":
                yield_per_tile = 6
            elif crop_name == "CARROT":
                yield_per_tile = 4
            elif crop_name == "MELON":
                yield_per_tile = 2

            # Planting day
            daily_actions[start_day] += (n_tiles * 2)

            if is_ongoing:
                for d in range(start_day + 1, end_day):
                    age = d - start_day
                    days_since_first = age - first_yield
                    if days_since_first >= 0 and (days_since_first % interval == 0) and ((days_since_first // interval) < max_yield_count):
                        daily_actions[d] += (n_tiles * 2)
                        if crop_name == "WHEAT":
                            daily_wheat_additions[d] += (n_tiles * yield_per_tile)
                        else:
                            daily_commercial_additions[d] += (n_tiles * yield_per_tile)
                    else:
                        if age % 2 == 1:
                            daily_actions[d] += n_tiles
            else:
                harvest_day = start_day + max_yield_day
                for d in range(start_day + 1, end_day):
                    age = d - start_day
                    if d == harvest_day:
                        daily_actions[d] += (n_tiles * 2)
                        if crop_name == "WHEAT":
                            daily_wheat_additions[d] += (n_tiles * yield_per_tile)
                        else:
                            daily_commercial_additions[d] += (n_tiles * yield_per_tile)
                    elif d < harvest_day:
                        w_start = (max_yield_day + 1) // 2
                        if age >= w_start:
                            daily_actions[d] += n_tiles

        sim_wheat = sum(cnt for item, cnt in snapshot.shed_inventory if item == "WHEAT")
        sim_commercial = sum(cnt for item, cnt in snapshot.shed_inventory if item in ("CARROT", "MELON", "STRAWBERRY", "TOMATO"))
        sim_other = sum(cnt for item, cnt in snapshot.shed_inventory if item not in ("WHEAT", "CARROT", "MELON", "STRAWBERRY", "TOMATO"))

        daily_sale_limit = min(20, active_workers * 10)
        has_market = False
        if snapshot.market_prices:
            has_market = any(p > 0 for _, p in snapshot.market_prices)
        elif raw_ctx and "market" in raw_ctx and hasattr(raw_ctx["market"], "prices"):
            has_market = any(p > 0 for p in raw_ctx["market"].prices.values())
        if not has_market:
            daily_sale_limit = 0

        for d in range(start_day, end_day):
            acts = daily_actions.get(d, 0)
            if acts > peak_daily_actions:
                peak_daily_actions = acts
            if acts > daily_action_capacity:
                return False, peak_shed, peak_daily_actions, f"labor_exceeded_day_{d}_{acts}_gt_{daily_action_capacity}"

            # 1. Planned sales from starting inventory
            rem_limit = daily_sale_limit
            if planned_sales and d in planned_sales:
                p_sale = planned_sales[d]
                com_sold = min(sim_commercial, p_sale)
                sim_commercial -= com_sold
                rem_p = p_sale - com_sold
                sim_wheat = max(0, sim_wheat - rem_p)
                rem_limit = max(0, daily_sale_limit - p_sale)

            # 2. Add incoming harvest additions
            comm_in = daily_commercial_additions.get(d, 0)
            wheat_in = daily_wheat_additions.get(d, 0)
            sim_commercial += comm_in
            sim_wheat += wheat_in

            # Check peak shed on harvest arrival (must not exceed 100 before/during delivery)
            current_shed = sim_wheat + sim_commercial + sim_other
            if current_shed > peak_shed:
                peak_shed = current_shed
            if current_shed > 100:
                return False, peak_shed, peak_daily_actions, f"storage_overflow_day_{d}_{current_shed}_gt_100"

            # 3. Feasible sales of incoming commercial crops
            if rem_limit > 0 and daily_sale_limit > 0:
                comm_sell = min(sim_commercial, rem_limit)
                sim_commercial -= comm_sell

        return True, peak_shed, peak_daily_actions, None

    def evaluate(self, snapshot: ShadowSnapshot, raw_ctx: Optional[Dict[str, Any]] = None) -> ShadowResult:
        """Run complete shadow evaluation on the frozen snapshot.

        Enforces read-only isolation, real substrate integration, and event-driven replanning.
        """
        start_t = time.perf_counter()

        plan = self.farm_plan
        if raw_ctx is not None:
            plan.update_from_observation(raw_ctx)
            self.ledger.update_from_observation(raw_ctx)

        self.ledger.day = snapshot.day
        self.ledger.hour = snapshot.hour
        self.ledger.cash_on_hand = snapshot.money
        plan.day = snapshot.day
        plan.hour = snapshot.hour
        if plan.state == StrategicState.SW_NOT_COMMITTED and snapshot.day >= 4:
            plan.state = StrategicState.SW_PREPARING
        if plan.state == StrategicState.SW_PREPARING and (
            snapshot.day >= plan.expansion_target.earliest_feasible_day or snapshot.money >= 2200
        ):
            plan.state = StrategicState.SW_READY

        is_event_turn = (
            snapshot.hour == 0 or
            snapshot.day != self.last_replan_day or
            ("SW" in snapshot.unlocked_quadrants and plan.state == StrategicState.SW_READY)
        )
        if is_event_turn:
            self.last_replan_day = snapshot.day

        # 1. Candidate Portfolios & Opportunity-Cost Evaluation (Sequential Trajectory)
        sw_tiles = [(x, y) for y in range(5, 10) for x in range(0, 5) if (x, y) != (4, 5)]
        candidate_portfolios = self.cohort_planner.generate_candidate_portfolios(snapshot.day, sw_tiles)

        # 2. Feed & Storage Projections
        feed_status = self.ledger.project_feed_balance(horizon_days=3)
        storage_status = self.ledger.project_storage_timeline(horizon_hours=72)

        market_inv_dict = dict(snapshot.market_inventories)

        # 3. Grounded Core Workload Evaluation
        core_tasks = self._build_core_tasks(snapshot, raw_ctx, horizon_days=3)
        core_cert = self.certificate_evaluator.evaluate_multi_day(
            current_day=snapshot.day,
            current_hour=snapshot.hour,
            worker_count=snapshot.active_worker_count,
            tasks=core_tasks,
            horizon_hours=72,
        )

        # Estimate Core baseline harvest units and revenue WITHOUT SW
        core_crop_harvests: Dict[str, int] = {}
        if raw_ctx and "farm" in raw_ctx:
            farm_obj = raw_ctx["farm"]
            for t in farm_obj.iter_tiles():
                is_sw_tile = (t.x < 5 and t.y >= 5)
                if is_sw_tile or not getattr(t, "is_plant", False):
                    continue
                crop_name = getattr(t, "crop", None)
                if not crop_name:
                    continue
                cd = CROPS.get(crop_name, {})
                planted_day = getattr(t, "planted_day", snapshot.day)
                is_ongoing = cd.get("ongoing", False)
                first_yield = cd.get("first_yield_day", 2)
                interval = cd.get("interval", 2)
                max_yield_count = cd.get("max_yield", 6)
                max_yield_day = cd.get("max_yield_day", 4)

                yield_per_harvest = 1
                if crop_name == "WHEAT":
                    yield_per_harvest = 6
                elif crop_name == "CARROT":
                    yield_per_harvest = 4
                elif crop_name == "MELON":
                    yield_per_harvest = 2

                if is_ongoing:
                    for d in range(snapshot.day, 30):
                        age = d - planted_day
                        days_since_first = age - first_yield
                        if days_since_first >= 0 and (days_since_first % interval == 0) and ((days_since_first // interval) < max_yield_count):
                            core_crop_harvests[crop_name] = core_crop_harvests.get(crop_name, 0) + yield_per_harvest
                else:
                    harvest_day = planted_day + max_yield_day
                    if snapshot.day <= harvest_day < 30:
                        core_crop_harvests[crop_name] = core_crop_harvests.get(crop_name, 0) + yield_per_harvest
        else:
            for crop_name in ("CARROT", "MELON", "WHEAT", "STRAWBERRY", "TOMATO"):
                cnt = dict(snapshot.tiles_summary).get(crop_name, 0)
                if cnt > 0:
                    y_mult = 6 if crop_name == "WHEAT" else (4 if crop_name == "CARROT" else (2 if crop_name == "MELON" else 1))
                    core_crop_harvests[crop_name] = cnt * y_mult

        # Core livestock baseline revenue WITHOUT SW (milk and wool)
        core_livestock_revenue_without = 0.0
        num_cows = 0
        num_sheep = 0
        if raw_ctx and "farm" in raw_ctx:
            for t in raw_ctx["farm"].iter_tiles():
                if getattr(t, "is_animal", False) or getattr(t, "kind", None) == "PASTURE":
                    sp = getattr(t, "animal", None)
                    if sp == "COW":
                        num_cows += 1
                    elif sp == "SHEEP":
                        num_sheep += 1
        elif snapshot.animals_summary:
            for sp, cnt in snapshot.animals_summary:
                if sp == "COW":
                    num_cows += cnt
                elif sp == "SHEEP":
                    num_sheep += cnt

        days_remaining = max(0, 30 - snapshot.day)
        mkt_prices_dict = dict(snapshot.market_prices) if snapshot.market_prices else {}
        if num_cows > 0:
            cow_yields_remaining = days_remaining // 2
            est_milk_units = num_cows * cow_yields_remaining * 3
            milk_price = float(mkt_prices_dict.get("MILK", 10.0))
            core_livestock_revenue_without += est_milk_units * milk_price

        if num_sheep > 0:
            sheep_yields_remaining = days_remaining // 3
            est_wool_units = num_sheep * sheep_yields_remaining * 2
            wool_price = float(mkt_prices_dict.get("WOOL", 12.0))
            core_livestock_revenue_without += est_wool_units * wool_price

        core_gross_revenue_without = 0.0
        for c_name, c_units in core_crop_harvests.items():
            if c_units > 0:
                inv = market_inv_dict.get(c_name, 0)
                core_gross_revenue_without += float(total_revenue_estimate(c_name, inv, c_units))

        # Include livestock product yields in core revenue
        core_gross_revenue_without += core_livestock_revenue_without

        days_left = max(0, 30 - snapshot.day)
        core_daily_wages_without = snapshot.active_worker_count * 8 * days_left
        actual_sw_unlocked = ("SW" in snapshot.unlocked_quadrants or 3 in snapshot.unlocked_quadrants)
        baseline_land_spent = 2000.0 if actual_sw_unlocked else 0.0
        virtual_money = snapshot.money + baseline_land_spent - self.virtual_land_cost_paid
        sw_land_cost = 0.0 if self.virtual_sw_owned else 2000.0
        projected_terminal_cash_without = virtual_money + core_gross_revenue_without - core_daily_wages_without

        portfolio_evals = []

        candidates_evaluated_count = len(candidate_portfolios)
        candidates_admitted_count = 0
        candidates_delayed_count = 0
        candidates_downsized_count = 0
        candidates_rejected_count = 0

        for port in candidate_portfolios:
            total_crop_profit = 0.0
            total_seed_cost = 0.0
            cohort_names = []
            sim_market_inv = dict(market_inv_dict)
            sw_gross_revenue = 0.0
            sw_units_by_crop: Dict[str, int] = {}

            # Sequential Pricing Evaluation
            for crop_name, n_units, tiles in port["allocations"]:
                c_cohort = self.cohort_planner.build_candidate_crop_cohort(
                    cohort_id=f"shadow_{crop_name.lower()}_{snapshot.day}",
                    crop=crop_name,
                    region="SW",
                    tiles=tiles,
                    plant_day=snapshot.day,
                    is_discretionary=True,
                )
                eval_res = self.cohort_planner.evaluate_opportunity_cost(
                    candidate=c_cohort,
                    displaced_cohorts=[],
                    market_inventory=sim_market_inv,
                    existing_supply=0,
                    feed_deficit_risk=not feed_status["is_feed_safe"],
                )
                total_crop_profit += eval_res.delta_final_cash
                total_seed_cost += c_cohort.seed_cost
                sw_gross_revenue += eval_res.expected_gross_revenue
                sw_units_by_crop[crop_name] = sw_units_by_crop.get(crop_name, 0) + c_cohort.market_supply_units
                cohort_names.append(c_cohort.cohort_id)
                sim_market_inv[crop_name] = sim_market_inv.get(crop_name, 0) + c_cohort.market_supply_units

            # Core cannibalization loss from price depression
            core_cannibalization_loss = 0.0
            for c_name, c_units in core_crop_harvests.items():
                sw_u = sw_units_by_crop.get(c_name, 0)
                if c_units > 0 and sw_u > 0:
                    m_inv = market_inv_dict.get(c_name, 0)
                    rev_without_sw = float(total_revenue_estimate(c_name, m_inv, c_units))
                    rev_with_sw = float(total_revenue_estimate(c_name, m_inv + sw_u, c_units))
                    dep_loss = max(0.0, rev_without_sw - rev_with_sw)
                    core_cannibalization_loss += dep_loss

            # Serviceability Certification for Candidate Portfolio BEFORE Recommending
            cand_sw_tasks = self._build_candidate_sw_tasks(port, snapshot, horizon_days=3)
            combined_tasks = list(core_tasks) + cand_sw_tasks
            cand_cert = self.certificate_evaluator.evaluate_multi_day(
                current_day=snapshot.day,
                current_hour=snapshot.hour,
                worker_count=snapshot.active_worker_count,
                tasks=combined_tasks,
                horizon_hours=72,
            )

            # Realistic storage sales projection
            feasible_sales = self._project_feasible_sales(
                snapshot, core_crop_harvests, port, raw_ctx=raw_ctx
            )

            # Full economic lifecycle certification through Day 29
            lifecycle_feasible, peak_shed, peak_acts, lc_reason = self._evaluate_candidate_lifecycle(
                port, snapshot, raw_ctx=raw_ctx, planned_sales=feasible_sales
            )

            # Displaced core value and incremental labor
            displaced_core_value = 0.0
            if getattr(cand_cert, "displaced_core_tasks", None):
                for t in cand_cert.displaced_core_tasks:
                    if t.op == "HARVEST":
                        c_name = "WHEAT"
                        t_id_lower = t.task_id.lower()
                        if "carrot" in t_id_lower:
                            c_name = "CARROT"
                        elif "melon" in t_id_lower:
                            c_name = "MELON"
                        elif "strawberry" in t_id_lower:
                            c_name = "STRAWBERRY"
                        elif "tomato" in t_id_lower:
                            c_name = "TOMATO"
                        y_mult = 6 if c_name == "WHEAT" else (4 if c_name == "CARROT" else (2 if c_name == "MELON" else 1))
                        p_val = dict(snapshot.market_prices).get(c_name, 25.0)
                        displaced_core_value += float(y_mult * p_val)
                    elif t.op == "FEED":
                        displaced_core_value += 400.0
                    else:
                        displaced_core_value += 35.0

            sw_incremental_labor_cost = 0.0
            if not cand_cert.feasible and cand_cert.binding_resource in ("WORKER_HOURS", "LABOR"):
                needed_hires = max(0, (-cand_cert.minimum_slack + 23) // 24)
                sw_incremental_labor_cost = needed_hires * (100.0 + 8.0 * days_left)

            feed_opportunity_cost = 0.0
            if not feed_status["is_feed_safe"]:
                deficit_units = max(1, feed_status.get("deficit_units", 1) if isinstance(feed_status.get("deficit_units"), (int, float)) else 1)
                wheat_spot = dict(snapshot.market_prices).get("WHEAT", 25.0)
                feed_opportunity_cost = float(deficit_units * (wheat_spot * 1.5 + 20.0))

            storage_loss_penalty = 0.0
            if not lifecycle_feasible and "storage_overflow" in (lc_reason or ""):
                overflow_units = 10
                if lc_reason:
                    parts = lc_reason.split("_")
                    for idx_p, part in enumerate(parts):
                        if part == "gt" and idx_p > 0:
                            try:
                                peak_val = int(parts[idx_p - 1])
                                overflow_units = max(1, peak_val - 100)
                            except (ValueError, IndexError):
                                pass
                avg_crop_price = 35.0
                if port.get("allocations"):
                    c_names = [a[0] for a in port["allocations"]]
                    prices = [dict(snapshot.market_prices).get(cn, 35.0) for cn in c_names]
                    if prices:
                        avg_crop_price = sum(prices) / len(prices)
                storage_loss_penalty = float(overflow_units * avg_crop_price)

            # Genuine WITH/WITHOUT whole-farm delta:
            delta_fc = (
                sw_gross_revenue
                - total_seed_cost
                - sw_land_cost
                - core_cannibalization_loss
                - displaced_core_value
                - sw_incremental_labor_cost
                - feed_opportunity_cost
                - storage_loss_penalty
            )

            projected_terminal_cash_with = projected_terminal_cash_without + delta_fc

            is_serviceable = cand_cert.feasible and lifecycle_feasible
            is_admitted = is_serviceable and (delta_fc > 0)

            if is_admitted:
                candidates_admitted_count += 1
            else:
                if delta_fc <= 0:
                    candidates_rejected_count += 1
                elif not cand_cert.feasible:
                    if port.get("tiles_used", 0) > 8:
                        candidates_downsized_count += 1
                    else:
                        candidates_delayed_count += 1
                else:
                    candidates_rejected_count += 1

            portfolio_evals.append({
                "portfolio": port,
                "total_crop_profit": total_crop_profit,
                "total_seed_cost": total_seed_cost,
                "sw_gross_revenue": sw_gross_revenue,
                "core_cannibalization_loss": core_cannibalization_loss,
                "displaced_core_value": displaced_core_value,
                "sw_incremental_labor_cost": sw_incremental_labor_cost,
                "feed_opportunity_cost": feed_opportunity_cost,
                "storage_loss_penalty": storage_loss_penalty,
                "delta_fc": delta_fc,
                "projected_terminal_cash_with": projected_terminal_cash_with,
                "cohort_names": cohort_names,
                "cert": cand_cert,
                "serviceable": is_serviceable,
                "admitted": is_admitted,
                "lifecycle_feasible": lifecycle_feasible,
                "peak_shed": peak_shed,
                "peak_daily_actions": peak_acts,
                "lc_reason": lc_reason,
            })

        # Select the best ADMITTED candidate portfolio (or best candidate for telemetry)
        admitted_portfolios = [p for p in portfolio_evals if p["admitted"]]
        if admitted_portfolios:
            best_entry = max(admitted_portfolios, key=lambda p: p["delta_fc"])
            best_portfolio_data = (best_entry["portfolio"], best_entry["delta_fc"], best_entry["cohort_names"])
            best_delta = best_entry["delta_fc"]
            cert_result = best_entry["cert"]
            best_seed_cost = best_entry["total_seed_cost"]
            best_sw_gross = best_entry["sw_gross_revenue"]
            best_cannibalization = best_entry["core_cannibalization_loss"]
            best_displaced_val = best_entry["displaced_core_value"]
            best_inc_labor = best_entry["sw_incremental_labor_cost"]
            best_feed_opp = best_entry["feed_opportunity_cost"]
            best_storage_penalty = best_entry["storage_loss_penalty"]
            best_terminal_with = best_entry["projected_terminal_cash_with"]
            lifecycle_feasible_best = best_entry["lifecycle_feasible"]
            full_peak_shed = best_entry["peak_shed"]
            full_peak_acts = best_entry["peak_daily_actions"]
        else:
            positive_portfolios = [p for p in portfolio_evals if p["delta_fc"] > 0]
            if positive_portfolios:
                best_entry = max(positive_portfolios, key=lambda p: p["delta_fc"])
            else:
                best_entry = max(portfolio_evals, key=lambda p: p["delta_fc"]) if portfolio_evals else None

            best_portfolio_data = None
            best_delta = best_entry["delta_fc"] if best_entry else -sw_land_cost
            cert_result = best_entry["cert"] if best_entry else core_cert
            best_seed_cost = best_entry["total_seed_cost"] if best_entry else 0.0
            best_sw_gross = best_entry["sw_gross_revenue"] if best_entry else 0.0
            best_cannibalization = best_entry["core_cannibalization_loss"] if best_entry else 0.0
            best_displaced_val = best_entry["displaced_core_value"] if best_entry else 0.0
            best_inc_labor = best_entry["sw_incremental_labor_cost"] if best_entry else 0.0
            best_feed_opp = best_entry["feed_opportunity_cost"] if best_entry else 0.0
            best_storage_penalty = best_entry["storage_loss_penalty"] if best_entry else 0.0
            best_terminal_with = best_entry["projected_terminal_cash_with"] if best_entry else (projected_terminal_cash_without - sw_land_cost)
            lifecycle_feasible_best = best_entry["lifecycle_feasible"] if best_entry else True
            full_peak_shed = best_entry["peak_shed"] if best_entry else storage_status.get("peak_usage", 0)
            full_peak_acts = best_entry["peak_daily_actions"] if best_entry else 0

        # 4. Decision Compilation & Rich Baseline Disagreement Tracking
        disagreements = []
        baseline_intents_dict = dict(snapshot.baseline_intents)
        baseline_buys_land = bool(baseline_intents_dict.get("buy_land", False))

        # Check SW purchase recommendation (Pre-Purchase Certification)
        sw_recommended = False
        sw_reject_reason = None
        sw_rec_status = "REJECT"

        if self.virtual_sw_owned:
            sw_rec_status = "OWNED"
            sw_recommended = False
            sw_reject_reason = "already_purchased_in_virtual_plan"
        else:
            if plan.state == StrategicState.SW_READY or (plan.state == StrategicState.SW_PREPARING and virtual_money >= 2200):
                if virtual_money < 2200:
                    sw_reject_reason = f"insufficient_cash (${virtual_money:.1f} < $2,200)"
                    sw_rec_status = "DELAY"
                elif not feed_status["is_feed_safe"]:
                    sw_reject_reason = f"feed_deficit_risk ({'; '.join(feed_status.get('unfed_reasons', []))})"
                    sw_rec_status = "DELAY"
                elif best_portfolio_data is None:
                    if any(p["delta_fc"] > 0 and not p["cert"].feasible for p in portfolio_evals):
                        sw_reject_reason = f"labor_congestion (binding={cert_result.binding_resource})"
                        sw_rec_status = "DOWNSIZE" if candidates_downsized_count > 0 else "DELAY"
                    elif any(p["delta_fc"] <= 0 for p in portfolio_evals):
                        sw_reject_reason = f"negative_whole_farm_delta_fc (best delta ${best_delta:.1f} after land cost ${sw_land_cost:.1f})"
                        sw_rec_status = "REJECT"
                    else:
                        sw_reject_reason = f"no_serviceable_candidate_portfolio (core binding={core_cert.binding_resource})"
                        sw_rec_status = "REJECT"
                elif best_delta <= 0:
                    sw_reject_reason = f"negative_whole_farm_delta_fc (best delta ${best_delta:.1f} after land cost ${sw_land_cost:.1f})"
                    sw_rec_status = "REJECT"
                elif not cert_result.feasible:
                    sw_reject_reason = f"service_certificate_infeasible (binding={cert_result.binding_resource})"
                    sw_rec_status = "DELAY"
                elif not lifecycle_feasible_best:
                    sw_reject_reason = f"lifecycle_infeasible ({best_entry.get('lc_reason') if best_entry else 'overflow'})"
                    sw_rec_status = "REJECT"
                else:
                    sw_recommended = True
                    sw_rec_status = "PURCHASE"
                    self.virtual_sw_owned = True
                    self.virtual_sw_purchase_day = snapshot.day
                    self.virtual_land_cost_paid = 2000.0
                    if best_portfolio_data:
                        self.virtual_sw_purchase_tranche = best_portfolio_data[0].get("name")
                        self.virtual_sw_purchase_tiles = best_portfolio_data[0].get("tiles_used", 0)
            else:
                sw_rec_status = "DELAY" if snapshot.day < 8 else "REJECT"
                if virtual_money < 2200:
                    sw_reject_reason = f"insufficient_cash (${virtual_money:.1f} < $2,200)"
                else:
                    sw_reject_reason = f"expansion_prerequisites_unmet (state={plan.state.value})"

        # Disagreement 1: LAND_PURCHASE_MISMATCH (Policy Disagreement)
        if baseline_buys_land != sw_recommended:
            disagreements.append({
                "type": "LAND_PURCHASE_MISMATCH",
                "category": "GENUINE_POLICY_DISAGREEMENT",
                "baseline_decision": baseline_buys_land,
                "shadow_decision": sw_recommended,
                "is_policy_disagreement": True,
                "metrics": {
                    "money": snapshot.money,
                    "best_delta": best_delta,
                    "cert_feasible": cert_result.feasible,
                    "best_portfolio": best_portfolio_data[0]["name"] if best_portfolio_data else None,
                    "sw_recommendation_status": sw_rec_status,
                },
                "reason": (
                    f"Shadow planner recommends SW purchase on Day {snapshot.day} based on certified 72h forward feasibility and candidate portfolio delta (${best_delta:.1f})"
                    if sw_recommended else
                    f"Shadow planner rejects land buy: {sw_reject_reason or 'unmet prerequisites'}"
                ),
            })

        # Disagreement 2: LIVESTOCK_ADMISSION_MISMATCH (Policy Disagreement)
        baseline_animal_raw = baseline_intents_dict.get("buy_animal")
        baseline_animals: Dict[str, int] = {}
        if isinstance(baseline_animal_raw, dict):
            baseline_animals = {k: int(v) for k, v in baseline_animal_raw.items() if int(v) > 0}
        elif isinstance(baseline_animal_raw, (list, tuple)):
            for item in baseline_animal_raw:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    baseline_animals[str(item[0])] = int(item[1])
                elif isinstance(item, str):
                    baseline_animals[item] = 1
        elif isinstance(baseline_animal_raw, str) and baseline_animal_raw:
            baseline_animals = {baseline_animal_raw: 1}

        if baseline_animals:
            rejected_species = []
            reasons = []
            total_animal_cost = 0
            incremental_daily_feed = 0

            tile_summary_dict = dict(snapshot.tiles_summary)
            farm_obj = raw_ctx.get("farm") if raw_ctx else None

            # Calculate empty structure tiles and housing capacity
            structure_free_tiles: Dict[str, List[Tuple[int, int]]] = {}
            if farm_obj:
                for t in farm_obj.iter_tiles():
                    k = getattr(t, "kind", "")
                    if k in ("PASTURE", "COOP"):
                        is_occ = (getattr(t, "animal", None) is not None) or getattr(t, "is_animal", False)
                        if not is_occ:
                            structure_free_tiles.setdefault(k, []).append((t.x, t.y))
            else:
                for st in ("PASTURE", "COOP"):
                    total_st = tile_summary_dict.get(st, 0)
                    occ_st = sum(tile_summary_dict.get(a, 0) for a, d in ANIMALS.items() if d.get("structure") == st)
                    free_cnt = max(0, total_st - occ_st)
                    structure_free_tiles[st] = [(4, 5)] * free_cnt

            allocated_tiles: List[Tuple[int, int]] = []

            for sp, count in baseline_animals.items():
                sp_info = ANIMALS.get(sp.upper(), {})
                sp_cost = sp_info.get("cost", 400) * count
                total_animal_cost += sp_cost
                incremental_daily_feed += count
                req_struct = sp_info.get("structure")

                if req_struct:
                    total_struct_count = 0
                    if farm_obj:
                        total_struct_count = sum(1 for t in farm_obj.iter_tiles() if getattr(t, "kind", "") == req_struct)
                    else:
                        total_struct_count = tile_summary_dict.get(req_struct, 0)

                    if total_struct_count == 0:
                        rejected_species.append(sp)
                        reasons.append(f"missing_structure_{req_struct}")
                    else:
                        available_tiles = structure_free_tiles.get(req_struct, [])
                        if len(available_tiles) < count:
                            rejected_species.append(sp)
                            reasons.append(f"insufficient_housing_{req_struct}")
                        else:
                            for _ in range(count):
                                allocated_tiles.append(available_tiles.pop(0))

            # 1. Cash solvency check (cost + $200 buffer)
            if snapshot.money < (total_animal_cost + 200):
                if not rejected_species:
                    rejected_species = list(baseline_animals.keys())
                reasons.append("insufficient_cash")

            # 2. Feed safety check
            if not feed_status["is_feed_safe"]:
                if not rejected_species:
                    rejected_species = list(baseline_animals.keys())
                reasons.append("feed_deficit_risk")
            elif feed_status.get("min_projected_balance", 0) < (incremental_daily_feed * 3):
                if not rejected_species:
                    rejected_species = list(baseline_animals.keys())
                reasons.append("incremental_feed_deficit")

            # 3. Labor / Certificate check with distinct placement & incremental feeding tasks
            anim_tasks = list(core_tasks)
            for d_offset in range(3):
                eval_day = snapshot.day + d_offset
                if eval_day >= 30:
                    break
                for idx, t_pos in enumerate(allocated_tiles):
                    anim_tasks.append(
                        ServiceTask(
                            task_id=f"feed_inc_{idx}_{t_pos[0]}_{t_pos[1]}_d{eval_day}",
                            op="FEED",
                            pos=t_pos,
                            region="NW" if t_pos[1] < 5 else "SW",
                            day=eval_day,
                            hour_deadline=20,
                            tier=CommitmentTier.HARD,
                            estimated_duration_actions=1,
                        )
                    )
            anim_cert = self.certificate_evaluator.evaluate_multi_day(
                current_day=snapshot.day,
                current_hour=snapshot.hour,
                worker_count=snapshot.active_worker_count,
                tasks=anim_tasks,
                horizon_hours=72,
            )
            if not anim_cert.feasible:
                if not rejected_species:
                    rejected_species = list(baseline_animals.keys())
                reasons.append(f"cert_binding_{anim_cert.binding_resource}")

            if rejected_species:
                disagreements.append({
                    "type": "LIVESTOCK_ADMISSION_MISMATCH",
                    "category": "GENUINE_POLICY_DISAGREEMENT",
                    "baseline_decision": baseline_animals,
                    "shadow_decision": {sp: 0 for sp in rejected_species},
                    "is_policy_disagreement": True,
                    "metrics": {
                        "cert_feasible": anim_cert.feasible,
                        "feed_safe": feed_status["is_feed_safe"],
                        "min_projected_balance": feed_status.get("min_projected_balance", 0),
                        "total_animal_cost": total_animal_cost,
                        "money": snapshot.money,
                        "reasons": reasons,
                    },
                    "reason": f"Livestock counterfactual evaluation rejects admission: {', '.join(reasons)}",
                })

        # Disagreement 3: CROP_PORTFOLIO_MISMATCH (Policy Disagreement)
        sw_active_now = ("SW" in snapshot.unlocked_quadrants or 3 in snapshot.unlocked_quadrants)
        if sw_active_now and best_portfolio_data:
            port_crops = [alloc[0] for alloc in best_portfolio_data[0]["allocations"]]
            baseline_sw_target = baseline_intents_dict.get("sw_plant_crop") or baseline_intents_dict.get("sw_crop")
            if baseline_sw_target and baseline_sw_target not in port_crops:
                disagreements.append({
                    "type": "CROP_PORTFOLIO_MISMATCH",
                    "category": "GENUINE_POLICY_DISAGREEMENT",
                    "baseline_decision": baseline_sw_target,
                    "shadow_decision": port_crops,
                    "is_policy_disagreement": True,
                    "metrics": {"portfolio_delta": best_delta, "portfolio_name": best_portfolio_data[0]["name"]},
                    "reason": f"Shadow candidate portfolio ({best_portfolio_data[0]['name']}) selects {port_crops} (delta ${best_delta:.1f}) instead of baseline SW target {baseline_sw_target}",
                })

        # Disagreement 4: HIRE_SCHEDULE_MISMATCH (Policy Disagreement)
        baseline_hire_count = int(baseline_intents_dict.get("hire", 0))
        if "hire" not in baseline_intents_dict and "hire_hand" in baseline_intents_dict:
            baseline_hire_count = 1 if baseline_intents_dict.get("hire_hand") else 0

        shadow_proposed_hires = 0
        if cert_result.binding_resource in ("WORKER_HOURS", "LABOR") and not cert_result.feasible and snapshot.money >= 100:
            shadow_proposed_hires = 1

        if baseline_hire_count != shadow_proposed_hires:
            disagreements.append({
                "type": "HIRE_SCHEDULE_MISMATCH",
                "category": "GENUINE_POLICY_DISAGREEMENT",
                "baseline_decision": baseline_hire_count,
                "shadow_decision": shadow_proposed_hires,
                "is_policy_disagreement": True,
                "metrics": {
                    "baseline_hires": baseline_hire_count,
                    "shadow_proposed_hires": shadow_proposed_hires,
                    "binding_resource": cert_result.binding_resource,
                    "cert_feasible": cert_result.feasible,
                },
                "reason": f"Labor certificate binding={cert_result.binding_resource}, feasible={cert_result.feasible}, shadow recommends {shadow_proposed_hires} hires vs baseline {baseline_hire_count}",
            })

        # Disagreement 5: FEED_ASSUMPTION_MISMATCH (Diagnostic Warning)
        if not feed_status["is_feed_safe"]:
            baseline_buy_wheat = int(baseline_intents_dict.get("buy_wheat", 0))
            baseline_prot_feed = int(baseline_intents_dict.get("protected_feed_wheat", 0))
            disagreements.append({
                "type": "FEED_ASSUMPTION_MISMATCH",
                "category": "SHADOW_DIAGNOSTIC_WARNING",
                "baseline_decision": {
                    "buy_wheat": baseline_buy_wheat,
                    "protected_feed_wheat": baseline_prot_feed,
                },
                "shadow_decision": "FEED_DEFICIT_RISK",
                "is_policy_disagreement": False,
                "metrics": {
                    "min_projected_balance": feed_status.get("min_projected_balance", 0),
                    "day_0_feasible": feed_status.get("day_0_feasible", False),
                    "unfed_reasons": feed_status.get("unfed_reasons", []),
                },
                "reason": f"Physical route projection indicates feed deficit: {'; '.join(feed_status.get('unfed_reasons', ['insufficient accessible wheat']))}",
            })

        # Disagreement 6: STORAGE_CONGESTION_WARNING (Diagnostic Warning)
        peak_shed = storage_status.get("peak_usage", 0)
        expected_overflow = storage_status.get("expected_overflow", 0)
        if peak_shed > 85 or expected_overflow > 0:
            disagreements.append({
                "type": "STORAGE_CONGESTION_WARNING",
                "category": "SHADOW_DIAGNOSTIC_WARNING",
                "baseline_decision": "NO_CONGESTION_HANDLING",
                "shadow_decision": {
                    "peak_usage": peak_shed,
                    "expected_overflow": expected_overflow,
                    "discarded_products": storage_status.get("discarded_products", {}),
                    "overflow_workers": storage_status.get("overflow_workers", []),
                },
                "is_policy_disagreement": False,
                "metrics": {
                    "peak_usage": peak_shed,
                    "expected_overflow": expected_overflow,
                    "peak_carried_units": storage_status.get("peak_carried_units", 0),
                },
                "reason": f"Projected peak storage {peak_shed}/100 exceeds safe threshold (85) or midnight overflow {expected_overflow} units detected",
            })

        # Disagreement 7: MARKET_VALUATION_DISCREPANCY (Diagnostic)
        market_disc = []
        for prod, inv in snapshot.market_inventories:
            dep_loss = self.cohort_planner.estimate_price_depression_loss(prod, 10, inv)
            if dep_loss > 100:
                market_disc.append({
                    "product": prod,
                    "market_inv": inv,
                    "depression_loss_10_units": dep_loss,
                })
        if market_disc:
            disagreements.append({
                "type": "MARKET_VALUATION_DISCREPANCY",
                "category": "UNRESOLVED_COMPARISON",
                "baseline_decision": "NOMINAL_PRICING",
                "shadow_decision": "SEQUENTIAL_DEPRESSION_AWARE",
                "is_policy_disagreement": False,
                "metrics": {"discrepancies": market_disc},
                "reason": f"Significant price depression detected on: {[m['product'] for m in market_disc]}",
            })

        proposed_crops = best_portfolio_data[2] if (best_portfolio_data and sw_recommended) else (
            ["SW_TRANCHE_1_WHEAT_STRAWBERRY"] if sw_recommended else []
        )

        # Count observed animals for uncertainty flags
        num_animals_observed = 0
        if raw_ctx and "farm" in raw_ctx:
            for t in raw_ctx["farm"].iter_tiles():
                if getattr(t, "is_animal", False) or (getattr(t, "animal", None) is not None) or getattr(t, "kind", None) in ANIMALS:
                    num_animals_observed += 1
        elif snapshot.animals_summary:
            num_animals_observed = sum(cnt for _, cnt in snapshot.animals_summary)
        else:
            num_animals_observed = sum(cnt for k, cnt in snapshot.tiles_summary if k in ANIMALS)

        uncertainty_flags: List[str] = []
        if any(dep.get("depression_loss_10_units", 0) > 100 for dep in market_disc):
            uncertainty_flags.append("PRICE_DEPRESSION_ESTIMATE")
        if num_animals_observed > 0:
            uncertainty_flags.append("HERD_FEED_ASSUMPTION")
        if any(p.get("serviceable") and not p.get("lifecycle_feasible") for p in portfolio_evals):
            uncertainty_flags.append("STORAGE_FLOW_CONGESTION")

        decision = ShadowDecision(
            strategic_state=plan.state.value,
            target_sw_day=plan.expansion_target.target_day,
            sw_purchase_recommended=sw_recommended,
            proposed_crop_cohorts=proposed_crops,
            proposed_livestock_cohorts=[],
            proposed_hires=shadow_proposed_hires,
            disagreements_with_baseline=disagreements,
            selected_portfolio=best_portfolio_data[0] if best_portfolio_data else None,
            market_valuation_discrepancies=market_disc,
            sw_recommendation_status=sw_rec_status,
            baseline_sw_purchase=baseline_buys_land,
            core_only_cert_feasible=core_cert.feasible,
            combined_cert_feasible=cert_result.feasible,
            lifecycle_workload_feasible=lifecycle_feasible_best,
            binding_resource=cert_result.binding_resource,
            binding_deadline=cert_result.binding_hour,
            portfolio_delta_fc=best_delta,
            sw_land_cost=sw_land_cost,
            sw_seed_cost=best_seed_cost,
            sw_incremental_labor_cost=best_inc_labor,
            sw_gross_revenue=best_sw_gross,
            core_cannibalization_loss=best_cannibalization,
            displaced_core_value=best_displaced_val,
            feed_opportunity_cost=best_feed_opp,
            storage_loss_penalty=best_storage_penalty,
            projected_terminal_cash_without=projected_terminal_cash_without,
            projected_terminal_cash_with=best_terminal_with,
            candidates_evaluated_count=candidates_evaluated_count,
            candidates_admitted_count=candidates_admitted_count,
            candidates_delayed_count=candidates_delayed_count,
            candidates_downsized_count=candidates_downsized_count,
            candidates_rejected_count=candidates_rejected_count,
            verified_service_feasible=(cert_result.feasible and lifecycle_feasible_best),
            economic_uncertainty_flags=uncertainty_flags,
            virtual_sw_owned=self.virtual_sw_owned,
            virtual_sw_purchase_day=self.virtual_sw_purchase_day,
            virtual_cash=virtual_money,
            actual_sw_unlocked=actual_sw_unlocked,
            selected_candidate_certificate=serialize_candidate_certificate(
                cert_result,
                best_portfolio_data[0] if best_portfolio_data else None,
                snapshot.day,
                snapshot.hour,
            ) if cert_result is not None else None,
        )

        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        self.latencies_ms.append(elapsed_ms)

        diagnostics = ShadowDiagnostics(
            latency_ms=elapsed_ms,
            event_replan_triggered=is_event_turn,
            resource_slack=cert_result.minimum_slack,
            feed_is_safe=feed_status["is_feed_safe"],
            cash_projected_available=self.ledger.project_available_cash(snapshot.day, snapshot.hour),
            binding_resource=cert_result.binding_resource,
            repair_options_count=len(cert_result.repair_options),
            storage_is_safe=(storage_status.get("peak_usage", 0) <= 85 and storage_status.get("expected_overflow", 0) == 0),
            lifecycle_feasible=lifecycle_feasible_best,
            full_lifecycle_peak_shed=full_peak_shed,
            full_lifecycle_peak_daily_actions=full_peak_acts,
        )

        result = ShadowResult(
            decision=decision,
            certificate=cert_result,
            diagnostics=diagnostics,
        )
        self.latest_result = result
        return result

    def get_latency_stats(self) -> Dict[str, float]:
        """Compute p50, p95, and max execution latency in milliseconds."""
        if not self.latencies_ms:
            return {"p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0, "count": 0}
        sorted_lat = sorted(self.latencies_ms)
        n = len(sorted_lat)
        p50 = sorted_lat[int(0.50 * n)]
        p95 = sorted_lat[min(n - 1, int(0.95 * n))]
        max_lat = sorted_lat[-1]
        return {
            "p50_ms": round(p50, 3),
            "p95_ms": round(p95, 3),
            "max_ms": round(max_lat, 3),
            "count": n,
        }


# Module singleton
_SHADOW_PLANNER_INSTANCE: Optional[WholeFarmPlanner] = None


def get_whole_farm_planner() -> WholeFarmPlanner:
    """Return the singleton WholeFarmPlanner instance."""
    global _SHADOW_PLANNER_INSTANCE
    if _SHADOW_PLANNER_INSTANCE is None:
        _SHADOW_PLANNER_INSTANCE = WholeFarmPlanner()
    return _SHADOW_PLANNER_INSTANCE


def reset_whole_farm_planner() -> None:
    """Hard-reset the planner instance between matches across all aliases."""
    global _SHADOW_PLANNER_INSTANCE
    _SHADOW_PLANNER_INSTANCE = WholeFarmPlanner()
    reset_farm_plan()
    for k in ("strategy.whole_farm_planner", "agent.strategy.whole_farm_planner"):
        mod = sys.modules.get(k)
        if mod is not None and mod is not sys.modules.get(__name__) and hasattr(mod, "_SHADOW_PLANNER_INSTANCE"):
            mod._SHADOW_PLANNER_INSTANCE = _SHADOW_PLANNER_INSTANCE
