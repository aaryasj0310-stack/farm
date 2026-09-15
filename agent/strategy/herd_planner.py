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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "desired_herd": self.desired_herd,
            "desired_cows": self.desired_cows,
            "desired_sheep": self.desired_sheep,
            "desired_geese": self.desired_geese,
            "required_pastures": self.required_pastures,
            "required_coops": self.required_coops,
            "horizon_days": self.horizon_days,
            "marginal_value_sequence": self.marginal_value_sequence,
            "rationale": self.rationale,
        }

    def __repr__(self) -> str:
        return (
            f"DynamicHerdPlan(cows={self.desired_cows}, sheep={self.desired_sheep}, geese={self.desired_geese}, "
            f"req_pastures={self.required_pastures}, req_coops={self.required_coops}, horizon={self.horizon_days}d)"
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
    if day >= C4_LIVESTOCK_CUTOFF_DAY:
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
                    "species": "NONE",
                    "candidate_num": 0,
                    "net_val": 0.0,
                    "accepted": False,
                    "reason": f"baseline_existing_herd_infeasible: {existing_res.blocking_reason}",
                    "execution_status": "rejected",
                    "feasibility_diag": existing_res.to_dict(),
                }],
                horizon_days=horizon_days,
                rationale="baseline_existing_herd_infeasible",
            )
        target_cap = herd_cap
    else:
        eff_max_sustainable = max_sustainable if max_sustainable is not None else herd_cap
        target_cap = min(herd_cap, eff_max_sustainable)

    # Infrastructure build cost allowance:
    # A planned prospective animal must earn enough to pay for its $100 pasture fence + $25 build action + logistics
    housing_build_hurdle = 150.0

    while sum(shadow_herd.values()) < target_cap:
        curr_total = sum(shadow_herd.values())
        base_evals: Dict[str, Dict[str, Any]] = {}
        stress_evals: Dict[str, Dict[str, Any]] = {}
        cand_results: Dict[str, Any] = {}

        # 1. Evaluate COW
        if shadow_herd["COW"] < cow_cap and (curr_total + 1) <= target_cap:
            cand_feasible = True
            cand_res = None
            if feed_ledger is not None:
                cand_res = evaluate_incremental_candidate(feed_ledger, "COW")
                cand_feasible = cand_res.feasible

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
                    stress_evals["COW"] = eval_c_stress

        # 2. Evaluate SHEEP
        if shadow_herd["SHEEP"] < sheep_cap and (curr_total + 1) <= target_cap:
            cand_feasible = True
            cand_res = None
            if feed_ledger is not None:
                cand_res = evaluate_incremental_candidate(feed_ledger, "SHEEP")
                cand_feasible = cand_res.feasible

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
                    stress_evals["SHEEP"] = eval_s_stress

        # 3. Evaluate GOOSE (strict zero-geese check: evaluate real ROI)
        if (curr_total + 1) <= target_cap:
            cand_feasible = True
            cand_res = None
            if feed_ledger is not None:
                cand_res = evaluate_incremental_candidate(feed_ledger, "GOOSE")
                cand_feasible = cand_res.feasible

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
                    stress_evals["GOOSE"] = eval_g_stress

        if not base_evals:
            if feed_ledger is not None and (curr_total < target_cap):
                marginal_value_seq.append("No candidates feasible under FeedResourceLedger -> STOP")
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
            decision_records.append({
                "species": best_sp,
                "candidate_num": next_count,
                "net_val": round(best_val, 2),
                "accepted": False,
                "reason": "below_housing_hurdle",
                "execution_status": "rejected",
            })
            break

        # ACCEPT candidate into forward shadow state
        status = "admitted"
        feed_diag = None
        if feed_ledger is not None:
            best_cand_res = cand_results[best_sp]
            commit_candidate_reservation(feed_ledger, best_cand_res)
            if best_cand_res.execution_confidence in ("guarded", "conditional"):
                status = "provisional_guarded"
            feed_diag = best_cand_res.to_dict()

        shadow_herd[best_sp] += 1
        switch_note = f" (SWITCH from {diag.get('baseline_best')} [gap {diag.get('relative_gap', 0):.1%}])" if diag.get("switched") else ""
        marginal_value_seq.append(f"{best_sp} #{next_count}: +${best_val:.0f}{switch_note}")
        rec = {
            "species": best_sp,
            "candidate_num": next_count,
            "net_val": round(best_val, 2),
            "accepted": True,
            "reason": "economically_justified",
            "guarded_diag": diag,
            "execution_status": status,
        }
        if feed_diag is not None:
            rec["feed_feasibility"] = feed_diag
        decision_records.append(rec)

    req_pastures = shadow_herd["COW"] + shadow_herd["SHEEP"]
    req_coops = shadow_herd["GOOSE"]

    return DynamicHerdPlan(
        desired_herd=shadow_herd,
        required_pastures=req_pastures,
        required_coops=req_coops,
        marginal_value_sequence=marginal_value_seq,
        decision_records=decision_records,
        horizon_days=horizon_days,
        rationale=f"shadow_econ_plan_c{shadow_herd['COW']}_s{shadow_herd['SHEEP']}_g{shadow_herd['GOOSE']}",
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
    needed_pastures = max(0, dynamic_herd_plan.required_pastures - total_committed_pastures)

    total_committed_coops = int(existing_coops) + int(reserved_coop_tiles)
    needed_coops = max(0, dynamic_herd_plan.required_coops - total_committed_coops)

    return {
        "needed_pastures": needed_pastures,
        "needed_coops": needed_coops,
    }
