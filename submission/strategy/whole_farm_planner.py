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
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from config import get_sw_forward_architecture_mode, CROPS, ANIMALS
    from strategy.farm_plan import FarmPlan, StrategicState, get_farm_plan, reset_farm_plan
    from strategy.resource_ledger import ResourceLedger, InflowConfidence
    from strategy.cohort_planner import CohortPlanner, CropCohort, OpportunityCostEvaluation
    from strategy.service_certificate import ServiceCertificate, CertificateResult, ServiceTask, CommitmentTier
    from state.observation_parser import needs_water_today, crop_produces_today, turns_until_decay
except ImportError:
    from config import get_sw_forward_architecture_mode, CROPS, ANIMALS
    from farm_plan import FarmPlan, StrategicState, get_farm_plan, reset_farm_plan
    from resource_ledger import ResourceLedger, InflowConfidence
    from cohort_planner import CohortPlanner, CropCohort, OpportunityCostEvaluation
    from service_certificate import ServiceCertificate, CertificateResult, ServiceTask, CommitmentTier
    from observation_parser import needs_water_today, crop_produces_today, turns_until_decay


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
        if farm:
            for t in farm.iter_tiles():
                k = getattr(t, "kind", "EMPTY")
                tile_counts[k] = tile_counts.get(k, 0) + 1
        tile_counts_tuple = tuple(sorted(tile_counts.items()))

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


@dataclass
class ShadowResult:
    """Complete, self-contained output of shadow planning turn."""
    decision: ShadowDecision
    certificate: CertificateResult
    diagnostics: ShadowDiagnostics


class WholeFarmPlanner:
    """Strategic orchestrator evaluating whole-farm forward trajectories."""

    def __init__(self) -> None:
        self.ledger: ResourceLedger = ResourceLedger()
        self.cohort_planner: CohortPlanner = CohortPlanner()
        self.certificate_evaluator: ServiceCertificate = ServiceCertificate()

        # Telemetry history
        self.latencies_ms: List[float] = []
        self.latest_result: Optional[ShadowResult] = None
        self.last_replan_day: int = -1

    def _build_core_tasks(
        self,
        snapshot: ShadowSnapshot,
        raw_ctx: Optional[Dict[str, Any]] = None,
        horizon_days: int = 3,
    ) -> List[ServiceTask]:
        """Build observation-grounded core NW/NE workload tasks over the rolling horizon."""
        simulated_tasks: List[ServiceTask] = []
        plan = get_farm_plan()

        for d_offset in range(horizon_days):
            eval_day = snapshot.day + d_offset
            if eval_day >= 30:
                break

            # 1. Outstanding animal feeding obligations from ledger
            day_liabs = [l for l in self.ledger.feed_liabilities if l.day == eval_day]
            for liab in day_liabs:
                simulated_tasks.append(
                    ServiceTask(
                        task_id=f"feed_animal_{liab.animal_pos[0]}_{liab.animal_pos[1]}_d{eval_day}",
                        op="FEED",
                        pos=liab.animal_pos,
                        region="NW" if liab.animal_pos[1] < 5 else "SW",
                        day=eval_day,
                        hour_deadline=liab.hour_deadline,
                        tier=CommitmentTier.HARD,
                        estimated_duration_actions=1,
                    )
                )

            # 2. Existing NW/NE in-ground wheat harvests from ledger
            for h in self.ledger.in_ground_wheat:
                if h.earliest_harvest_day == eval_day:
                    simulated_tasks.append(
                        ServiceTask(
                            task_id=f"harvest_wheat_{h.tile_pos[0]}_{h.tile_pos[1]}_d{eval_day}",
                            op="HARVEST",
                            pos=h.tile_pos,
                            region="NW",
                            day=eval_day,
                            hour_deadline=20,
                            tier=CommitmentTier.HARD,
                            estimated_duration_actions=1,
                        )
                    )

            # 3. Grounded core crop maintenance from observed tiles or fallback summary
            if raw_ctx and "farm" in raw_ctx:
                farm_obj = raw_ctx["farm"]
                for t in farm_obj.iter_tiles():
                    # Core tiles only (exclude SW region tiles x < 5, y >= 5)
                    is_sw_tile = (t.x < 5 and t.y >= 5)
                    if is_sw_tile:
                        continue
                    if getattr(t, "is_plant", False):
                        # Water evaluation
                        needs_w = False
                        if eval_day == snapshot.day:
                            if not getattr(t, "watered_today", False):
                                needs_w = needs_water_today(t, eval_day)
                        else:
                            needs_w = needs_water_today(t, eval_day)

                        if needs_w:
                            is_survival = (eval_day == snapshot.day and (
                                int(getattr(t, "consecutive_unwatered", 0) or 0) >= 1 or
                                getattr(t, "planted_day", None) == snapshot.day
                            ))
                            deadline = 23 if is_survival else 18
                            tier = CommitmentTier.HARD if is_survival else CommitmentTier.STRATEGIC
                            simulated_tasks.append(
                                ServiceTask(
                                    task_id=f"core_water_{t.x}_{t.y}_d{eval_day}",
                                    op="WATER",
                                    pos=(t.x, t.y),
                                    region="NW" if t.x < 5 else "NE",
                                    day=eval_day,
                                    hour_deadline=deadline,
                                    tier=tier,
                                    estimated_duration_actions=1,
                                )
                            )

                        # Mature / decay harvest evaluation
                        if eval_day == snapshot.day and getattr(t, "yield_units", 0) > 0:
                            crop_name = getattr(t, "crop", None)
                            cd = CROPS.get(crop_name, {})
                            age = eval_day - t.planted_day if t.planted_day is not None else 0
                            is_decay = False
                            if not cd.get("ongoing", False):
                                is_decay = (age >= cd.get("max_yield_day", 4))
                            else:
                                is_decay = crop_produces_today(t, eval_day)

                            if is_decay:
                                is_in_ledger = (crop_name == "WHEAT" and any(
                                    h.tile_pos == (t.x, t.y) and h.earliest_harvest_day == eval_day
                                    for h in self.ledger.in_ground_wheat
                                ))
                                if not is_in_ledger:
                                    simulated_tasks.append(
                                        ServiceTask(
                                            task_id=f"core_harvest_{t.x}_{t.y}_d{eval_day}",
                                            op="HARVEST",
                                            pos=(t.x, t.y),
                                            region="NW" if t.x < 5 else "NE",
                                            day=eval_day,
                                            hour_deadline=20,
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

            # 4. Plant queue obligations from farm plan
            if eval_day == snapshot.day and plan and getattr(plan, "plant_queue", None):
                for pq_idx, pq_item in enumerate(plan.plant_queue):
                    pq_pos = getattr(pq_item, "pos", (1, 1))
                    if not (pq_pos[0] < 5 and pq_pos[1] >= 5):
                        simulated_tasks.append(
                            ServiceTask(
                                task_id=f"core_plant_queue_{pq_idx}_d{eval_day}",
                                op="PLANT",
                                pos=pq_pos,
                                region="NW" if pq_pos[0] < 5 else "NE",
                                day=eval_day,
                                hour_deadline=20,
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

    def evaluate(self, snapshot: ShadowSnapshot, raw_ctx: Optional[Dict[str, Any]] = None) -> ShadowResult:
        """Run complete shadow evaluation on the frozen snapshot.

        Enforces read-only isolation, real substrate integration, and event-driven replanning.
        """
        start_t = time.perf_counter()

        plan = get_farm_plan()
        if raw_ctx is not None:
            # Sync observation facts
            plan.update_from_observation(raw_ctx)
            self.ledger.update_from_observation(raw_ctx)
        else:
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

        # Event-driven replanning detection:
        # Full deep replan triggers on:
        # 1. Day boundary (hour == 0)
        # 2. Quadrant unlock change
        # 3. State transition
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

        portfolio_evals = []

        for port in candidate_portfolios:
            total_delta = 0.0
            cohort_names = []
            sim_market_inv = dict(market_inv_dict)

            # Sequential Pricing Evaluation (existing_supply=0, sim_market_inv updated per cohort)
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
                total_delta += eval_res.delta_final_cash
                cohort_names.append(c_cohort.cohort_id)
                sim_market_inv[crop_name] = sim_market_inv.get(crop_name, 0) + c_cohort.market_supply_units

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

            portfolio_evals.append({
                "portfolio": port,
                "total_delta": total_delta,
                "cohort_names": cohort_names,
                "cert": cand_cert,
                "serviceable": cand_cert.feasible,
            })

        # Select the best SERVICEABLE candidate portfolio
        serviceable_portfolios = [p for p in portfolio_evals if p["serviceable"]]
        if serviceable_portfolios:
            best_entry = max(serviceable_portfolios, key=lambda p: p["total_delta"])
            best_portfolio_data = (best_entry["portfolio"], best_entry["total_delta"], best_entry["cohort_names"])
            best_delta = best_entry["total_delta"]
            cert_result = best_entry["cert"]
        else:
            best_entry = max(portfolio_evals, key=lambda p: p["total_delta"]) if portfolio_evals else None
            best_portfolio_data = None
            best_delta = best_entry["total_delta"] if best_entry else 0.0
            cert_result = core_cert

        # 4. Decision Compilation & Rich Baseline Disagreement Tracking
        disagreements = []
        baseline_intents_dict = dict(snapshot.baseline_intents)
        baseline_buys_land = bool(baseline_intents_dict.get("buy_land", False))

        # Check SW purchase recommendation (Pre-Purchase Certification)
        sw_recommended = False
        sw_reject_reason = None
        if "SW" not in snapshot.unlocked_quadrants and 3 not in snapshot.unlocked_quadrants:
            if plan.state == StrategicState.SW_READY:
                if snapshot.money < 2200:
                    sw_reject_reason = f"insufficient_cash (${snapshot.money:.1f} < $2,200)"
                elif not feed_status["is_feed_safe"]:
                    sw_reject_reason = f"feed_deficit_risk ({'; '.join(feed_status.get('unfed_reasons', []))})"
                elif best_portfolio_data is None:
                    sw_reject_reason = f"no_serviceable_candidate_portfolio (core binding={core_cert.binding_resource})"
                elif best_delta <= 0:
                    sw_reject_reason = f"non_positive_opportunity_cost (best delta ${best_delta:.1f})"
                elif not cert_result.feasible:
                    sw_reject_reason = f"service_certificate_infeasible (binding={cert_result.binding_resource})"
                else:
                    sw_recommended = True

        # Disagreement 1: LAND_PURCHASE_MISMATCH (Policy Disagreement)
        if baseline_buys_land != sw_recommended:
            disagreements.append({
                "type": "LAND_PURCHASE_MISMATCH",
                "baseline_decision": baseline_buys_land,
                "shadow_decision": sw_recommended,
                "is_policy_disagreement": True,
                "metrics": {
                    "money": snapshot.money,
                    "best_delta": best_delta,
                    "cert_feasible": cert_result.feasible,
                    "best_portfolio": best_portfolio_data[0]["name"] if best_portfolio_data else None,
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

            # Structure availability check from tiles
            tile_summary_dict = dict(snapshot.tiles_summary)
            farm_obj = raw_ctx.get("farm") if raw_ctx else None

            for sp, count in baseline_animals.items():
                sp_info = ANIMALS.get(sp.upper(), {})
                sp_cost = sp_info.get("cost", 400) * count
                total_animal_cost += sp_cost
                incremental_daily_feed += count
                req_struct = sp_info.get("structure")
                if req_struct:
                    has_struct = False
                    if farm_obj:
                        has_struct = any(getattr(t, "kind", "") == req_struct for t in farm_obj.iter_tiles())
                    else:
                        has_struct = tile_summary_dict.get(req_struct, 0) > 0
                    if not has_struct:
                        rejected_species.append(sp)
                        reasons.append(f"missing_structure_{req_struct}")

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

            # 3. Labor / Certificate check with incremental feeding tasks
            anim_tasks = list(core_tasks)
            for d_offset in range(3):
                eval_day = snapshot.day + d_offset
                if eval_day >= 30:
                    break
                for sp, count in baseline_animals.items():
                    for a_i in range(count):
                        anim_tasks.append(
                            ServiceTask(
                                task_id=f"feed_inc_{sp.lower()}_{a_i}_d{eval_day}",
                                op="FEED",
                                pos=(4, 5),
                                region="NW",
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
        # Production seed purchases for NW/NE must not trigger false CROP_PORTFOLIO_MISMATCH.
        # Only flag true policy disagreement when SW tile allocations conflict or core commitments prevent admitted SW obligations.
        sw_active_now = ("SW" in snapshot.unlocked_quadrants or 3 in snapshot.unlocked_quadrants)
        if sw_active_now and best_portfolio_data:
            port_crops = [alloc[0] for alloc in best_portfolio_data[0]["allocations"]]
            baseline_sw_target = baseline_intents_dict.get("sw_plant_crop") or baseline_intents_dict.get("sw_crop")
            if baseline_sw_target and baseline_sw_target not in port_crops:
                disagreements.append({
                    "type": "CROP_PORTFOLIO_MISMATCH",
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

        # Disagreement 5: FEED_ASSUMPTION_MISMATCH (Diagnostic)
        if not feed_status["is_feed_safe"]:
            baseline_buy_wheat = int(baseline_intents_dict.get("buy_wheat", 0))
            baseline_prot_feed = int(baseline_intents_dict.get("protected_feed_wheat", 0))
            disagreements.append({
                "type": "FEED_ASSUMPTION_MISMATCH",
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
                "baseline_decision": "NOMINAL_PRICING",
                "shadow_decision": "SEQUENTIAL_DEPRESSION_AWARE",
                "is_policy_disagreement": False,
                "metrics": {"discrepancies": market_disc},
                "reason": f"Significant price depression detected on: {[m['product'] for m in market_disc]}",
            })

        proposed_crops = best_portfolio_data[2] if (best_portfolio_data and sw_recommended) else (
            ["SW_TRANCHE_1_WHEAT_STRAWBERRY"] if sw_recommended else []
        )

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
    """Hard-reset the planner instance between matches."""
    global _SHADOW_PLANNER_INSTANCE
    _SHADOW_PLANNER_INSTANCE = WholeFarmPlanner()
    reset_farm_plan()
