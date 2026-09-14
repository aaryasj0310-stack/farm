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
from strategy.marginal_livestock_valuator import estimate_realized_marginal_animal_value


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
) -> DynamicHerdPlan:
    """Generate forward infrastructure herd targets using transactional shadow-state economics.

    Simulates adding prospective animals one by one into a shadow herd:
      - At each step, evaluates marginal counterfactual net value for COW, SHEEP, GOOSE.
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

    eff_max_sustainable = max_sustainable if max_sustainable is not None else herd_cap
    target_cap = min(herd_cap, eff_max_sustainable)

    # Infrastructure build cost allowance:
    # A planned prospective animal must earn enough to pay for its $100 pasture fence + $25 build action + logistics
    housing_build_hurdle = 150.0

    while sum(shadow_herd.values()) < target_cap:
        curr_total = sum(shadow_herd.values())
        evaluations: Dict[str, Dict[str, Any]] = {}

        # 1. Evaluate COW
        if shadow_herd["COW"] < cow_cap and (curr_total + 1) <= target_cap:
            eval_c = estimate_realized_marginal_animal_value(
                species="COW",
                day=day,
                current_animals=shadow_herd,
                market_inventory=market_inventory,
                empty_pastures=1,  # Infrastructure query: prospective pasture will be built
                crop_opportunity_val=crop_opportunity_val,
                town_shops=town_shops,
            )
            evaluations["COW"] = eval_c

        # 2. Evaluate SHEEP
        if shadow_herd["SHEEP"] < sheep_cap and (curr_total + 1) <= target_cap:
            eval_s = estimate_realized_marginal_animal_value(
                species="SHEEP",
                day=day,
                current_animals=shadow_herd,
                market_inventory=market_inventory,
                empty_pastures=1,  # Infrastructure query: prospective pasture will be built
                crop_opportunity_val=crop_opportunity_val,
                town_shops=town_shops,
            )
            evaluations["SHEEP"] = eval_s

        # 3. Evaluate GOOSE (strict zero-geese check: evaluate real ROI)
        if (curr_total + 1) <= target_cap:
            eval_g = estimate_realized_marginal_animal_value(
                species="GOOSE",
                day=day,
                current_animals=shadow_herd,
                market_inventory=market_inventory,
                empty_pastures=1,
                crop_opportunity_val=crop_opportunity_val,
                town_shops=town_shops,
            )
            evaluations["GOOSE"] = eval_g

        if not evaluations:
            break

        # Select candidate with highest marginal net realized value minus housing hurdle
        best_sp = max(evaluations.keys(), key=lambda sp: evaluations[sp]["net_realized_value"])
        best_val = evaluations[best_sp]["net_realized_value"]
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
            })
            break

        # ACCEPT candidate into forward shadow state
        shadow_herd[best_sp] += 1
        marginal_value_seq.append(f"{best_sp} #{next_count}: +${best_val:.0f}")
        decision_records.append({
            "species": best_sp,
            "candidate_num": next_count,
            "net_val": round(best_val, 2),
            "accepted": True,
            "reason": "economically_justified",
        })

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
