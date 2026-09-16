"""Forward Dynamic Herd Infrastructure Planner.

Decouples forward infrastructure planning (housing demand) from live purchase execution:
  1. Forward Infrastructure Horizon: Computes `DynamicHerdPlan` projecting economically justified
     herd size over the next 3-6 days via a transactional shadow simulation.
  2. Generic Housing Demand Interface: Exposes `get_forward_housing_demand()` so `pasture_planner`
     and `macro_planner` proactively reserve and construct structures without depending on static targets.
  3. Strict Safety Preservation: Dynamic/planned housing gives ZERO credit for selective late-purchases
     after Day 12; live purchase execution independently re-evaluates economics at order time.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple

from config import (
    ANIMALS,
    MARKET_I0,
    C4_LIVESTOCK_CUTOFF_DAY,
    SELECTIVE_LIVESTOCK_GATE_ENABLED,
    SELECTIVE_LIVESTOCK_GATE_THRESHOLD,
    SELECTIVE_LIVESTOCK_MAX_DAY,
    get_active_livestock_caps,
    get_point2_housing_fix_enabled,
)
from strategy.marginal_livestock_valuator import (
    estimate_realized_marginal_animal_value,
    select_guarded_livestock_candidate,
)


class DynamicHerdPlan:
    """Encapsulates the forward-looking economically justified herd and infrastructure requirements."""

    def __init__(
        self,
        desired_herd: Dict[str, int],
        required_pastures: int,
        required_coops: int,
        marginal_value_sequence: List[str],
        decision_records: List[Dict[str, Any]],
        horizon_days: int = 4,
        rationale: str = "",
        buy_animal_sequence: Optional[List[str]] = None,
        buy_animal: Optional[Dict[str, int]] = None,
        provisional_candidates: Optional[List[Dict[str, Any]]] = None,
        forward_desired_herd: Optional[Dict[str, int]] = None,
        forward_required_pastures: Optional[int] = None,
        forward_required_coops: Optional[int] = None,
        forward_only_candidates: Optional[List[Dict[str, Any]]] = None,
    ):
        self.desired_herd = dict(desired_herd)
        self.desired_cows = int(desired_herd.get("COW", 0))
        self.desired_sheep = int(desired_herd.get("SHEEP", 0))
        self.desired_geese = int(desired_herd.get("GOOSE", 0))
        self.required_pastures = int(required_pastures)
        self.required_coops = int(required_coops)
        self.marginal_value_sequence = list(marginal_value_sequence)
        self.decision_records = list(decision_records)
        self.horizon_days = int(horizon_days)
        self.rationale = str(rationale)

        # Forward infrastructure planning targets
        self.forward_desired_herd = dict(forward_desired_herd if forward_desired_herd is not None else self.desired_herd)
        self.forward_required_pastures = int(forward_required_pastures if forward_required_pastures is not None else self.required_pastures)
        self.forward_required_coops = int(forward_required_coops if forward_required_coops is not None else self.required_coops)
        self.forward_only_candidates = list(forward_only_candidates if forward_only_candidates is not None else [
            rec for rec in self.decision_records if rec.get("forward_only", False)
        ])

        # Enforce strict candidate classification and fail-safe exclusion of forward-only from purchase sequence
        if buy_animal_sequence is not None:
            self.buy_animal_sequence = list(buy_animal_sequence)
        else:
            self.buy_animal_sequence = [
                rec["species"] for rec in self.decision_records
                if rec.get("accepted", False)
                and not rec.get("forward_only", False)
                and rec.get("purchase_eligible", True)
                and rec.get("species") not in (None, "NONE")
            ]

        if buy_animal is not None:
            self.buy_animal = dict(buy_animal)
        else:
            self.buy_animal = {
                "COW": self.buy_animal_sequence.count("COW"),
                "SHEEP": self.buy_animal_sequence.count("SHEEP"),
                "GOOSE": self.buy_animal_sequence.count("GOOSE"),
            }

        if provisional_candidates is not None:
            self.provisional_candidates = list(provisional_candidates)
        else:
            self.provisional_candidates = []
            seq_counter = 0
            rej_counter = 0
            for rec in self.decision_records:
                is_accepted = bool(rec.get("accepted", False))
                is_forward_only = bool(rec.get("forward_only", False))
                sp = rec.get("species", "NONE")
                if is_accepted:
                    c_id = rec.get("candidate_id") or f"cand_{seq_counter}_{sp}"
                    s_idx = rec.get("sequence_index", seq_counter) if not is_forward_only else -1
                    if not is_forward_only:
                        seq_counter += 1
                    status = "forward_demand_only" if is_forward_only else "admitted"
                    exec_status = rec.get("execution_status", status)
                else:
                    c_id = rec.get("candidate_id") or f"cand_rej_{rej_counter}_{sp}"
                    s_idx = rec.get("sequence_index", -1)
                    rej_counter += 1
                    status = "rejected"
                    exec_status = "rejected"

                feed_diag = rec.get("feed_diagnostics") or rec.get("feed_feasibility") or rec.get("feasibility_diag") or {}
                self.provisional_candidates.append({
                    "candidate_id": c_id,
                    "sequence_index": s_idx,
                    "species": sp,
                    "provisional_status": status,
                    "feed_feasible": bool(rec.get("feed_feasible", is_accepted)),
                    "execution_status": exec_status,
                    "net_realized_value": float(rec.get("net_val", 0.0)),
                    "reason": str(rec.get("reason", "economically_justified" if is_accepted else "rejected")),
                    "feed_diagnostics": feed_diag,
                    "forward_only": is_forward_only,
                    "purchase_eligible": bool(rec.get("purchase_eligible", not is_forward_only)),
                })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "desired_herd": self.desired_herd,
            "desired_cows": self.desired_cows,
            "desired_sheep": self.desired_sheep,
            "desired_geese": self.desired_geese,
            "required_pastures": self.required_pastures,
            "required_coops": self.required_coops,
            "forward_desired_herd": self.forward_desired_herd,
            "forward_required_pastures": self.forward_required_pastures,
            "forward_required_coops": self.forward_required_coops,
            "forward_only_candidates": list(self.forward_only_candidates),
            "horizon_days": self.horizon_days,
            "marginal_value_sequence": self.marginal_value_sequence,
            "rationale": self.rationale,
            "buy_animal_sequence": list(self.buy_animal_sequence),
            "buy_animal": dict(self.buy_animal),
            "provisional_candidates": list(self.provisional_candidates),
        }

    def __repr__(self) -> str:
        return (
            f"DynamicHerdPlan(cows={self.desired_cows}, sheep={self.desired_sheep}, geese={self.desired_geese}, "
            f"req_pastures={self.required_pastures}, fwd_pastures={self.forward_required_pastures}, "
            f"req_coops={self.required_coops}, horizon={self.horizon_days}d)"
        )


def generate_dynamic_herd_plan(
    day: int,
    hour: int,
    current_herd: Dict[str, int],
    town_shops: Optional[List[str]] = None,
    market_inventory: Optional[Dict[str, float]] = None,
    max_sustainable: Optional[int] = None,
    active_caps: Optional[Dict[str, int]] = None,
    crop_opportunity_val: float = 0.0,
    horizon_days: int = 4,
    opponent_committed_supplies: Optional[Dict[str, Dict[int, float]]] = None,
    opponent_stress_supplies: Optional[Dict[str, Dict[int, float]]] = None,
    guard_threshold: float = 0.15,
    feed_ledger: Optional[Any] = None,
    late_selective_mode: bool = False,
    physical_housing_capacity: Optional[Dict[str, int]] = None,
) -> DynamicHerdPlan:
    """Generate forward infrastructure herd targets using transactional shadow-state economics.

    Simulates adding prospective animals one by one into a shadow herd:
      - At each step, evaluates marginal counterfactual net value for COW, SHEEP, GOOSE.
      - If feed_ledger is provided (Phase B authority):
          * Baseline existing herd must be feed-feasible; if not, stops immediately.
          * Candidates are filtered by incremental feed feasibility against residual ledger.
          * Selected candidate reservations are committed to feed_ledger.
          * Does not clamp target_cap by legacy scalar max_sustainable.
      - If feed_ledger is None:
          * Preserves legacy scalar max_sustainable cap behavior.
      - Picks the argmax profitable species.
      - Updates shadow herd, shadow future supply, shadow feed demand, and required housing.
      - Stops when no candidate clears the economic hurdle or constraints (caps, feed sustainability) bind.
      - Phase C2B: When late_selective_mode=True and day in [12, 14], restricts candidates to observed
        physical housing only, applies SELECTIVE_LIVESTOCK_GATE_THRESHOLD ($500 hurdle), and generates
        the authoritative late-selective candidate sequence.
    """
    day = int(day)
    caps = active_caps or get_active_livestock_caps()
    herd_cap = caps.get("HERD", 20)
    cow_cap = caps.get("COW", 19)
    sheep_cap = caps.get("SHEEP", 12)

    c0 = max(0, int(current_herd.get("COW", 0)))
    s0 = max(0, int(current_herd.get("SHEEP", 0)))
    g0 = max(0, int(current_herd.get("GOOSE", 0)))

    # On or after Day 12 cutoff: new infrastructure cannot amortize construction cost
    # Unless late_selective_mode is active (live mode only, Day 12-14, physical housing only)
    if day >= C4_LIVESTOCK_CUTOFF_DAY:
        if not (late_selective_mode and day <= SELECTIVE_LIVESTOCK_MAX_DAY):
            return DynamicHerdPlan(
                desired_herd={"COW": c0, "SHEEP": s0, "GOOSE": 0},
                required_pastures=c0 + s0,
                required_coops=g0,
                marginal_value_sequence=[f"Day {day} >= cutoff ({C4_LIVESTOCK_CUTOFF_DAY}) -> 0 new forward housing"],
                decision_records=[],
                horizon_days=horizon_days,
                rationale="late_season_cutoff",
            )

    # Initialize transactional shadow state
    shadow_herd = {"COW": c0, "SHEEP": s0, "GOOSE": 0}
    marginal_value_seq: List[str] = []
    decision_records: List[Dict[str, Any]] = []
    buy_animal_seq: List[str] = []

    if feed_ledger is not None:
        try:
            from strategy.feed_feasibility import (
                evaluate_existing_herd_feasibility,
                evaluate_incremental_candidate,
                commit_candidate_reservation,
            )
        except ImportError:
            from feed_feasibility import (
                evaluate_existing_herd_feasibility,
                evaluate_incremental_candidate,
                commit_candidate_reservation,
            )

        existing_ok, existing_res = evaluate_existing_herd_feasibility(feed_ledger)
        if not existing_ok:
            return DynamicHerdPlan(
                desired_herd=dict(shadow_herd),
                required_pastures=c0 + s0,
                required_coops=g0,
                marginal_value_sequence=[
                    f"Baseline existing herd infeasible ({existing_res.blocking_reason}) -> STOP"
                ],
                decision_records=[{
                    "candidate_id": "cand_rej_0_NONE",
                    "sequence_index": -1,
                    "species": "NONE",
                    "candidate_num": 0,
                    "net_val": 0.0,
                    "accepted": False,
                    "provisional_status": "rejected",
                    "feed_feasible": False,
                    "execution_status": "rejected",
                    "reason": f"baseline_existing_herd_infeasible: {existing_res.blocking_reason}",
                    "feed_diagnostics": existing_res.to_dict(),
                    "feasibility_diag": existing_res.to_dict(),
                }],
                horizon_days=horizon_days,
                rationale="baseline_existing_herd_infeasible",
                buy_animal_sequence=[],
                buy_animal={"COW": 0, "SHEEP": 0, "GOOSE": 0},
            )
        target_cap = herd_cap
    else:
        eff_max_sustainable = max_sustainable if max_sustainable is not None else herd_cap
        target_cap = min(herd_cap, eff_max_sustainable)

    # Infrastructure build cost allowance:
    # Under late selective mode: candidates must clear $500 hurdle and use physical housing only
    # Unless is_housing_fix is enabled on Days 12-13, which decouples forward housing evaluation
    is_housing_fix = get_point2_housing_fix_enabled() if callable(get_point2_housing_fix_enabled) else False

    if late_selective_mode and day >= C4_LIVESTOCK_CUTOFF_DAY:
        phys_avail_pastures = max(0, int(physical_housing_capacity.get("PASTURE", 0))) if physical_housing_capacity else 0
        phys_avail_coops = max(0, int(physical_housing_capacity.get("COOP", 0))) if physical_housing_capacity else 0
        housing_build_hurdle = float(SELECTIVE_LIVESTOCK_GATE_THRESHOLD)
        if is_housing_fix and day in (12, 13):
            # Days 12-13 with Fix H: allow forward housing evaluation up to herd cap
            avail_pastures = 999
            avail_coops = 999
            target_cap = herd_cap
        else:
            # Baseline or Day 14+: clamped strictly to physically observed capacity
            avail_pastures = phys_avail_pastures
            avail_coops = phys_avail_coops
            target_cap = (c0 + s0 + g0) + avail_pastures + avail_coops
    else:
        phys_avail_pastures = 999
        phys_avail_coops = 999
        avail_pastures = 999
        avail_coops = 999
        housing_build_hurdle = 150.0

    while sum(shadow_herd.values()) < target_cap:
        curr_total = sum(shadow_herd.values())
        base_evals: Dict[str, Dict[str, Any]] = {}
        stress_evals: Dict[str, Dict[str, Any]] = {}
        cand_results: Dict[str, Any] = {}
        infeasible_feed_cands: Dict[str, Any] = {}

        pastures_used = (shadow_herd["COW"] - c0) + (shadow_herd["SHEEP"] - s0)
        coops_used = shadow_herd["GOOSE"] - g0

        is_forward_slot_pasture = (late_selective_mode and day >= C4_LIVESTOCK_CUTOFF_DAY and is_housing_fix and pastures_used >= phys_avail_pastures)
        is_forward_slot_coop = (late_selective_mode and day >= C4_LIVESTOCK_CUTOFF_DAY and is_housing_fix and coops_used >= phys_avail_coops)

        rem_prod_days = max(0, 29 - day)
        forward_pasture_cost = 150.0 + 25.0 + max(0.0, float(crop_opportunity_val)) + (1.0 * rem_prod_days * 1.0)
        forward_coop_cost = 100.0 + 25.0 + max(0.0, float(crop_opportunity_val)) + (1.0 * rem_prod_days * 1.0)

        # 1. Evaluate COW
        cow_housing_ok = (not late_selective_mode or day < C4_LIVESTOCK_CUTOFF_DAY or pastures_used < avail_pastures)
        if shadow_herd["COW"] < cow_cap and (curr_total + 1) <= target_cap and cow_housing_ok:
            cand_feasible = True
            cand_res = None
            if feed_ledger is not None:
                cand_res = evaluate_incremental_candidate(feed_ledger, "COW")
                cand_feasible = cand_res.feasible
                if not cand_feasible:
                    infeasible_feed_cands["COW"] = cand_res

            if cand_feasible:
                eval_c_base = estimate_realized_marginal_animal_value(
                    species="COW",
                    day=day,
                    current_animals=shadow_herd,
                    market_inventory=market_inventory,
                    empty_pastures=1,  # Infrastructure query: prospective pasture will be built
                    crop_opportunity_val=crop_opportunity_val,
                    town_shops=town_shops,
                    opponent_committed_supply=(opponent_committed_supplies.get("MILK") if opponent_committed_supplies else None),
                )
                if is_forward_slot_pasture:
                    eval_c_base = dict(eval_c_base)
                    eval_c_base["net_realized_value"] = round(eval_c_base["net_realized_value"] - forward_pasture_cost, 2)
                    eval_c_base["housing_charge"] = round(forward_pasture_cost, 2)
                    eval_c_base["forward_only"] = True
                base_evals["COW"] = eval_c_base
                if cand_res is not None:
                    cand_results["COW"] = cand_res
                if opponent_stress_supplies is not None:
                    eval_c_stress = estimate_realized_marginal_animal_value(
                        species="COW",
                        day=day,
                        current_animals=shadow_herd,
                        market_inventory=market_inventory,
                        empty_pastures=1,
                        crop_opportunity_val=crop_opportunity_val,
                        town_shops=town_shops,
                        opponent_committed_supply=opponent_stress_supplies.get("MILK"),
                    )
                    if is_forward_slot_pasture:
                        eval_c_stress = dict(eval_c_stress)
                        eval_c_stress["net_realized_value"] = round(eval_c_stress["net_realized_value"] - forward_pasture_cost, 2)
                        eval_c_stress["housing_charge"] = round(forward_pasture_cost, 2)
                        eval_c_stress["forward_only"] = True
                    stress_evals["COW"] = eval_c_stress

        # 2. Evaluate SHEEP
        sheep_housing_ok = (not late_selective_mode or day < C4_LIVESTOCK_CUTOFF_DAY or pastures_used < avail_pastures)
        if shadow_herd["SHEEP"] < sheep_cap and (curr_total + 1) <= target_cap and sheep_housing_ok:
            cand_feasible = True
            cand_res = None
            if feed_ledger is not None:
                cand_res = evaluate_incremental_candidate(feed_ledger, "SHEEP")
                cand_feasible = cand_res.feasible
                if not cand_feasible:
                    infeasible_feed_cands["SHEEP"] = cand_res

            if cand_feasible:
                eval_s_base = estimate_realized_marginal_animal_value(
                    species="SHEEP",
                    day=day,
                    current_animals=shadow_herd,
                    market_inventory=market_inventory,
                    empty_pastures=1,  # Infrastructure query: prospective pasture will be built
                    crop_opportunity_val=crop_opportunity_val,
                    town_shops=town_shops,
                    opponent_committed_supply=(opponent_committed_supplies.get("WOOL") if opponent_committed_supplies else None),
                )
                if is_forward_slot_pasture:
                    eval_s_base = dict(eval_s_base)
                    eval_s_base["net_realized_value"] = round(eval_s_base["net_realized_value"] - forward_pasture_cost, 2)
                    eval_s_base["housing_charge"] = round(forward_pasture_cost, 2)
                    eval_s_base["forward_only"] = True
                base_evals["SHEEP"] = eval_s_base
                if cand_res is not None:
                    cand_results["SHEEP"] = cand_res
                if opponent_stress_supplies is not None:
                    eval_s_stress = estimate_realized_marginal_animal_value(
                        species="SHEEP",
                        day=day,
                        current_animals=shadow_herd,
                        market_inventory=market_inventory,
                        empty_pastures=1,
                        crop_opportunity_val=crop_opportunity_val,
                        town_shops=town_shops,
                        opponent_committed_supply=opponent_stress_supplies.get("WOOL"),
                    )
                    if is_forward_slot_pasture:
                        eval_s_stress = dict(eval_s_stress)
                        eval_s_stress["net_realized_value"] = round(eval_s_stress["net_realized_value"] - forward_pasture_cost, 2)
                        eval_s_stress["housing_charge"] = round(forward_pasture_cost, 2)
                        eval_s_stress["forward_only"] = True
                    stress_evals["SHEEP"] = eval_s_stress

        # 3. Evaluate GOOSE (strict zero-geese check: evaluate real ROI)
        goose_housing_ok = (not late_selective_mode or day < C4_LIVESTOCK_CUTOFF_DAY or coops_used < avail_coops)
        if (curr_total + 1) <= target_cap and goose_housing_ok:
            cand_feasible = True
            cand_res = None
            if feed_ledger is not None:
                cand_res = evaluate_incremental_candidate(feed_ledger, "GOOSE")
                cand_feasible = cand_res.feasible
                if not cand_feasible:
                    infeasible_feed_cands["GOOSE"] = cand_res

            if cand_feasible:
                eval_g_base = estimate_realized_marginal_animal_value(
                    species="GOOSE",
                    day=day,
                    current_animals=shadow_herd,
                    market_inventory=market_inventory,
                    empty_pastures=1,
                    crop_opportunity_val=crop_opportunity_val,
                    town_shops=town_shops,
                    opponent_committed_supply=(opponent_committed_supplies.get("EGG") if opponent_committed_supplies else None),
                )
                if is_forward_slot_coop:
                    eval_g_base = dict(eval_g_base)
                    eval_g_base["net_realized_value"] = round(eval_g_base["net_realized_value"] - forward_coop_cost, 2)
                    eval_g_base["housing_charge"] = round(forward_coop_cost, 2)
                    eval_g_base["forward_only"] = True
                base_evals["GOOSE"] = eval_g_base
                if cand_res is not None:
                    cand_results["GOOSE"] = cand_res
                if opponent_stress_supplies is not None:
                    eval_g_stress = estimate_realized_marginal_animal_value(
                        species="GOOSE",
                        day=day,
                        current_animals=shadow_herd,
                        market_inventory=market_inventory,
                        empty_pastures=1,
                        crop_opportunity_val=crop_opportunity_val,
                        town_shops=town_shops,
                        opponent_committed_supply=opponent_stress_supplies.get("EGG"),
                    )
                    if is_forward_slot_coop:
                        eval_g_stress = dict(eval_g_stress)
                        eval_g_stress["net_realized_value"] = round(eval_g_stress["net_realized_value"] - forward_coop_cost, 2)
                        eval_g_stress["housing_charge"] = round(forward_coop_cost, 2)
                        eval_g_stress["forward_only"] = True
                    stress_evals["GOOSE"] = eval_g_stress

        if not base_evals:
            if feed_ledger is not None and (curr_total < target_cap):
                marginal_value_seq.append("No candidates feasible under FeedResourceLedger -> STOP")
                for sp in ("COW", "SHEEP", "GOOSE"):
                    cand_res = infeasible_feed_cands.get(sp)
                    if cand_res is not None:
                        decision_records.append({
                            "candidate_id": f"cand_rej_{len(decision_records)}_{sp}",
                            "sequence_index": -1,
                            "species": sp,
                            "candidate_num": shadow_herd[sp] + 1,
                            "net_val": 0.0,
                            "accepted": False,
                            "provisional_status": "rejected",
                            "feed_feasible": False,
                            "execution_status": "rejected",
                            "reason": f"feed_infeasible: {cand_res.blocking_reason}",
                            "feed_diagnostics": cand_res.to_dict(),
                            "feed_feasibility": cand_res.to_dict(),
                        })
            break

        # Select candidate: guarded commitment awareness if stress test provided, otherwise argmax baseline
        if opponent_stress_supplies is not None:
            best_sp, chosen_eval, diag = select_guarded_livestock_candidate(
                base_evals, stress_evals, guard_threshold=guard_threshold
            )
            best_val = chosen_eval["net_realized_value"]
        else:
            best_sp = max(base_evals.keys(), key=lambda sp: base_evals[sp]["net_realized_value"])
            chosen_eval = base_evals[best_sp]
            best_val = chosen_eval["net_realized_value"]
            diag = {"switched": False}

        next_count = shadow_herd[best_sp] + 1

        # Check hurdle: must cover capital costs and prospective housing
        if best_val < housing_build_hurdle:
            marginal_value_seq.append(
                f"{best_sp} #{next_count}: ${best_val:.0f} -> STOP (below hurdle ${housing_build_hurdle:.0f})"
            )
            cand_diag = cand_results[best_sp].to_dict() if (best_sp in cand_results and cand_results[best_sp]) else {}
            decision_records.append({
                "candidate_id": f"cand_rej_{len(decision_records)}_{best_sp}",
                "sequence_index": -1,
                "species": best_sp,
                "candidate_num": next_count,
                "net_val": round(best_val, 2),
                "accepted": False,
                "provisional_status": "rejected",
                "feed_feasible": True,
                "execution_status": "rejected",
                "reason": "below_housing_hurdle" if not late_selective_mode else "below_selective_hurdle",
                "feed_diagnostics": cand_diag,
                "feed_feasibility": cand_diag,
            })
            break

        # ACCEPT candidate into forward shadow state
        is_best_forward_only = (
            late_selective_mode and day >= C4_LIVESTOCK_CUTOFF_DAY and is_housing_fix and (
                (best_sp in ("COW", "SHEEP") and pastures_used >= phys_avail_pastures)
                or (best_sp == "GOOSE" and coops_used >= phys_avail_coops)
            )
        )

        if is_best_forward_only:
            status = "forward_demand_only"
        elif late_selective_mode:
            status = "admitted_late_selective"
        else:
            status = "admitted"

        feed_diag = None
        if feed_ledger is not None:
            best_cand_res = cand_results[best_sp]
            commit_candidate_reservation(feed_ledger, best_cand_res)
            if best_cand_res.execution_confidence in ("guarded", "conditional"):
                status = "provisional_guarded" if not is_best_forward_only else "forward_demand_only"
            feed_diag = best_cand_res.to_dict()

        shadow_herd[best_sp] += 1
        if is_best_forward_only:
            seq_idx = -1
        else:
            seq_idx = len(buy_animal_seq)
            buy_animal_seq.append(best_sp)

        switch_note = f" (SWITCH from {diag.get('baseline_best')} [gap {diag.get('relative_gap', 0):.1%}])" if diag.get("switched") else ""
        fwd_note = " [FORWARD_HOUSING_DEMAND]" if is_best_forward_only else ""
        marginal_value_seq.append(f"{best_sp} #{next_count}: +${best_val:.0f}{switch_note}{fwd_note}")
        rec = {
            "candidate_id": f"cand_{'fwd_' + str(len(decision_records)) if is_best_forward_only else str(seq_idx)}_{best_sp}",
            "sequence_index": seq_idx,
            "species": best_sp,
            "candidate_num": next_count,
            "net_val": round(best_val, 2),
            "accepted": True,
            "forward_only": is_best_forward_only,
            "purchase_eligible": not is_best_forward_only,
            "provisional_status": "forward_demand_only" if is_best_forward_only else "admitted",
            "feed_feasible": True,
            "reason": "economically_justified_forward_housing" if is_best_forward_only else "economically_justified",
            "guarded_diag": diag,
            "execution_status": status,
            "housing_charge": chosen_eval.get("housing_charge", 0.0),
            "feed_diagnostics": feed_diag or {},
        }
        if feed_diag is not None:
            rec["feed_feasibility"] = feed_diag
        decision_records.append(rec)

    req_pastures = c0 + s0 + buy_animal_seq.count("COW") + buy_animal_seq.count("SHEEP")
    req_coops = g0 + buy_animal_seq.count("GOOSE")
    fwd_pastures = shadow_herd["COW"] + shadow_herd["SHEEP"]
    fwd_coops = shadow_herd["GOOSE"]

    return DynamicHerdPlan(
        desired_herd={"COW": c0 + buy_animal_seq.count("COW"), "SHEEP": s0 + buy_animal_seq.count("SHEEP"), "GOOSE": g0 + buy_animal_seq.count("GOOSE")},
        required_pastures=req_pastures,
        required_coops=req_coops,
        forward_desired_herd=shadow_herd,
        forward_required_pastures=fwd_pastures,
        forward_required_coops=fwd_coops,
        forward_only_candidates=[rec for rec in decision_records if rec.get("forward_only", False)],
        marginal_value_sequence=marginal_value_seq,
        decision_records=decision_records,
        horizon_days=horizon_days,
        rationale=f"shadow_econ_plan_c{shadow_herd['COW']}_s{shadow_herd['SHEEP']}_g{shadow_herd['GOOSE']}",
        buy_animal_sequence=buy_animal_seq,
    )


def get_forward_housing_demand(
    dynamic_herd_plan: DynamicHerdPlan,
    existing_pastures: int,
    reserved_pasture_tiles: int,
    existing_coops: int = 0,
    reserved_coop_tiles: int = 0,
) -> Dict[str, int]:
    """Calculate the net unreserved infrastructure demand for forward planning.

    Returns:
      {
        "needed_pastures": int,  # Net pasture fences to construct
        "needed_coops": int,     # Net coops to construct
      }
    """
    total_committed_pastures = int(existing_pastures) + int(reserved_pasture_tiles)
    req_pastures = getattr(dynamic_herd_plan, "forward_required_pastures", dynamic_herd_plan.required_pastures)
    needed_pastures = max(0, req_pastures - total_committed_pastures)

    total_committed_coops = int(existing_coops) + int(reserved_coop_tiles)
    req_coops = getattr(dynamic_herd_plan, "forward_required_coops", dynamic_herd_plan.required_coops)
    needed_coops = max(0, req_coops - total_committed_coops)

    return {
        "needed_pastures": needed_pastures,
        "needed_coops": needed_coops,
    }
