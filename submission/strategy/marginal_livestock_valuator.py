"""Market-aware marginal livestock valuation using sequential counterfactual inventory simulation.

Calculates the true realized marginal net value of adding one specific additional
animal (COW, SHEEP, or GOOSE) on day D, accounting for:
- Exact engine yield timing (gestation lag, intervals, care bonus)
- Sequential market inventory simulation with-candidate vs without-candidate:
  Inv(t+1) = max(1, Inv(t) + Supply(t) - Drain(t))
  so earlier unsold production depresses later batch prices
- Whole-farm counterfactual marginal product revenue:
  DeltaRev = Rev_with - Rev_without
  which naturally captures own-supply price depression on the existing herd
  with zero double-counting and zero separate heuristic penalty subtractions
- Authoritative live market pricing for feed (WHEAT) and fertilizer (FERTILIZER)
- Pasture / housing opportunity cost
- Exact conditional distribution over remaining future town shop unlocks
"""
from typing import Dict, Any, List, Optional, Tuple
import itertools

from config import MARKET_I0, ANIMALS
try:
    from market.price_math import market_price
except ImportError:
    from price_math import market_price

try:
    from strategy.baked_conditional_animal_prices import (
        UNLOCK_DAYS, TC_DEMAND, SHOP_DEMAND_RATES
    )
except ImportError:
    from baked_conditional_animal_prices import (
        UNLOCK_DAYS, TC_DEMAND, SHOP_DEMAND_RATES
    )


try:
    from strategy.price_forecast import PriceForecast
    _PRICE_FORECAST = PriceForecast.load()
except Exception:
    _PRICE_FORECAST = None


def derive_opponent_committed_livestock_scenarios(
    opp_farm,
    current_day: int,
) -> Dict[str, Dict[str, Dict[int, float]]]:
    """Derive future committed supply for EGG, MILK, WOOL under LOW, BASE, HIGH scenarios.

    Uses only visible opponent animals physically placed on tiles and engine lifecycle rules.
    Does not predict sales, collection timing, or unplaced future purchases.
    """
    scenarios = {
        "LOW":  {"MILK": {t: 0.0 for t in range(current_day, 29)},
                 "WOOL": {t: 0.0 for t in range(current_day, 29)},
                 "EGG":  {t: 0.0 for t in range(current_day, 29)}},
        "BASE": {"MILK": {t: 0.0 for t in range(current_day, 29)},
                 "WOOL": {t: 0.0 for t in range(current_day, 29)},
                 "EGG":  {t: 0.0 for t in range(current_day, 29)}},
        "HIGH": {"MILK": {t: 0.0 for t in range(current_day, 29)},
                 "WOOL": {t: 0.0 for t in range(current_day, 29)},
                 "EGG":  {t: 0.0 for t in range(current_day, 29)}},
    }
    if opp_farm is None or current_day >= 28:
        return scenarios

    # Realization fractions:
    # LOW: 50% realization (delayed collection / uncared base 1 yield)
    # BASE: 85% realization (regular care bonus with calibrated delivery)
    # HIGH: 100% ceiling realization (full care + immediate daily sale)
    REALIZATION = {"LOW": 0.50, "BASE": 0.85, "HIGH": 1.00}

    for t in opp_farm.iter_tiles():
        if not getattr(t, "is_animal", False) or t.animal not in ANIMALS:
            continue

        # Dead or escaping animals produce 0
        if getattr(t, "consecutive_unfed", 0) >= 2:
            continue

        sp = t.animal
        prod = ANIMALS[sp]["product"]
        if prod not in ("MILK", "WOOL", "EGG"):
            continue

        info = ANIMALS[sp]
        first_yield_day = int(info["first_yield_day"])
        interval = int(info["interval"])
        max_held = int(info["max_held"])

        placed_day = getattr(t, "placed_day", None)
        held = getattr(t, "yield_units", 0) or 0
        if placed_day is not None:
            placed_day = int(placed_day)
            first_prod_day = placed_day + first_yield_day
        else:
            first_prod_day = (current_day + interval) if held > 0 else (current_day + 1)

        base_yield = 1.0
        cared_yield = 3.0 if sp == "COW" else (4.0 if sp == "SHEEP" else 2.0)

        # 1. Uncollected ripe units sitting on tile today
        ripe_now = min(float(max_held), float(held))
        if ripe_now > 0:
            for sc, frac in REALIZATION.items():
                scenarios[sc][prod][current_day] += round(frac * ripe_now, 3)

        # 2. Future production schedules (only available on future days)
        for day_t in range(current_day + 1, 29):
            if day_t < first_prod_day:
                continue
            if (day_t - first_prod_day) % interval == 0:
                scenarios["LOW"][prod][day_t] += round(REALIZATION["LOW"] * base_yield, 3)
                scenarios["BASE"][prod][day_t] += round(REALIZATION["BASE"] * cared_yield, 3)
                scenarios["HIGH"][prod][day_t] += round(REALIZATION["HIGH"] * cared_yield, 3)

    return scenarios


def derive_opponent_committed_livestock_supply(
    opp_farm,
    current_day: int,
    scenario: str = "BASE",
) -> Dict[str, Dict[int, float]]:
    """Convenience helper returning product -> {day: units} for specified scenario."""
    scenarios = derive_opponent_committed_livestock_scenarios(opp_farm, current_day)
    sc = str(scenario).upper()
    return scenarios.get(sc, scenarios["BASE"])


def derive_opponent_committed_livestock_stress_capacity(
    opp_farm,
    current_day: int,
) -> Dict[str, Dict[int, float]]:
    """Derive deterministic future livestock production capacity from visible opponent animals.

    Strictly satisfies Phase 2 requirements:
    - Uses 100% visible commitments on public tiles only.
    - Deterministic engine intervals and capacities (Cow: 3/2d, Sheep: 4/3d, Goose: 2/1d).
    - 0% behavioral discounts (no 85% realization assumption).
    - 0% speculative future purchases or future buildings.
    - Current ripe units sitting on tiles are credited on current_day.
    - Future batches are scheduled for day_t > current_day at exact interval cadence.
    """
    products = ("MILK", "WOOL", "EGG")
    stress_supply = {p: {t: 0.0 for t in range(current_day, 29)} for p in products}

    if opp_farm is None:
        return stress_supply

    for t in opp_farm.iter_tiles():
        if not getattr(t, "is_animal", False):
            continue
        sp = getattr(t, "animal", None)
        if not sp or sp not in ANIMALS:
            continue
        prod = ANIMALS[sp]["product"]
        if prod not in products:
            continue

        info = ANIMALS[sp]
        first_yield_day = int(info["first_yield_day"])
        interval = int(info["interval"])
        max_held = int(info["max_held"])

        placed_day = getattr(t, "placed_day", None)
        held = getattr(t, "yield_units", 0) or 0
        if placed_day is not None:
            placed_day = int(placed_day)
            first_prod_day = placed_day + first_yield_day
        else:
            first_prod_day = (current_day + interval) if held > 0 else (current_day + 1)

        cared_yield = 3.0 if sp == "COW" else (4.0 if sp == "SHEEP" else 2.0)

        # 1. Deterministic ripe units sitting on tile today
        ripe_now = min(float(max_held), float(held))
        if ripe_now > 0:
            stress_supply[prod][current_day] += ripe_now

        # 2. Future deterministic capacity at interval cadence
        for day_t in range(current_day + 1, 29):
            if day_t < first_prod_day:
                continue
            if (day_t - first_prod_day) % interval == 0:
                stress_supply[prod][day_t] += cared_yield

    return stress_supply


def select_guarded_livestock_candidate(
    baseline_evals: Dict[str, Dict[str, Any]],
    stress_evals: Optional[Dict[str, Dict[str, Any]]] = None,
    guard_threshold: float = 0.15,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Select candidate species using guarded commitment awareness.

    Enforces the core rule:
    - First evaluates baseline L0 marginal values.
    - Commitment-stress valuation may change the selected species ONLY if the
      L0 alternatives are already economically close (relative_gap <= guard_threshold).
    - Opponent commitments are NEVER allowed to overturn a large baseline advantage.

    Returns:
        (selected_species, selected_eval_dict, diagnostic_metadata)
    """
    if not baseline_evals:
        raise ValueError("baseline_evals cannot be empty")

    # Sort baseline candidates by net realized value descending
    sorted_baseline = sorted(
        baseline_evals.keys(),
        key=lambda s: baseline_evals[s].get("net_realized_value", -9999.0),
        reverse=True
    )
    baseline_best = sorted_baseline[0]
    baseline_best_val = baseline_evals[baseline_best].get("net_realized_value", -9999.0)

    baseline_second = sorted_baseline[1] if len(sorted_baseline) > 1 else None
    baseline_second_val = (
        baseline_evals[baseline_second].get("net_realized_value", -9999.0)
        if baseline_second else baseline_best_val
    )

    baseline_gap = max(0.0, baseline_best_val - baseline_second_val)
    ref_scale = max(abs(baseline_best_val), 1.0)
    relative_gap = baseline_gap / ref_scale

    diag = {
        "baseline_best": baseline_best,
        "baseline_best_val": baseline_best_val,
        "baseline_second": baseline_second,
        "baseline_second_val": baseline_second_val,
        "baseline_gap": round(baseline_gap, 2),
        "relative_gap": round(relative_gap, 4),
        "guard_threshold": guard_threshold,
        "stress_best": None,
        "stress_best_val": None,
        "switch_eligible": bool(relative_gap <= guard_threshold),
        "switched": False,
        "blocked_by_guard": False,
        "selected_species": baseline_best,
        "switch_reason": "none",
    }

    if not stress_evals:
        return baseline_best, baseline_evals[baseline_best], diag

    # Rank under stress
    sorted_stress = sorted(
        stress_evals.keys(),
        key=lambda s: stress_evals[s].get("net_realized_value", -9999.0),
        reverse=True
    )
    stress_best = sorted_stress[0]
    stress_best_val = stress_evals[stress_best].get("net_realized_value", -9999.0)
    diag["stress_best"] = stress_best
    diag["stress_best_val"] = stress_best_val

    if stress_best != baseline_best:
        if relative_gap <= guard_threshold:
            # Baseline was close; stress test reveals baseline choice is fragile
            diag["switched"] = True
            diag["blocked_by_guard"] = False
            diag["selected_species"] = stress_best
            diag["switch_reason"] = f"close_baseline_gap_{relative_gap:.1%}_le_{guard_threshold:.1%}"
            return stress_best, stress_evals[stress_best], diag
        else:
            # Baseline advantage was robust; guard blocked stress switch
            diag["switched"] = False
            diag["blocked_by_guard"] = True
            diag["selected_species"] = baseline_best
            diag["switch_reason"] = f"guard_blocked_gap_{relative_gap:.1%}_gt_{guard_threshold:.1%}"
            return baseline_best, baseline_evals[baseline_best], diag

    return baseline_best, baseline_evals[baseline_best], diag


def estimate_realized_marginal_animal_value(
    species: str,
    day: int,
    current_animals: Dict[str, int],
    market_inventory: Optional[Dict[str, float]] = None,
    empty_pastures: int = 0,
    crop_opportunity_val: float = 0.0,
    wheat_available_per_animal: float = 20.0,
    town_shops: Optional[List[str]] = None,
    opponent_committed_supply: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    """Calculate the realized marginal net value of adding ONE additional animal on `day`.

    Simulates day-by-day inventory from day `day` to 28 for with-candidate and without-candidate
    branches under one consistent joint future shop-unlock path:
        I(t+1) = max(1, I(t) + Supply(t) - Drain(t))
    and accumulates counterfactual revenue:
        DeltaRev = Rev_with - Rev_without
    """
    sp = str(species).upper()
    if sp not in ("COW", "SHEEP", "GOOSE"):
        return {
            "species": sp, "day": day, "viable": False,
            "net_realized_value": -9999.0, "reason": "unsupported_species"
        }

    day = int(day)
    rem_days = max(0, 29 - day)
    if rem_days <= 0 or day >= 28:
        return {
            "species": sp, "day": day, "viable": False,
            "net_realized_value": -9999.0, "reason": "season_ended"
        }

    cost = float(ANIMALS[sp]["cost"])
    prod_item = ANIMALS[sp]["product"]
    current_count = int(current_animals.get(sp, 0)) if current_animals else 0

    # 1. Exact Production Schedule and Yields (with authoritative engine care bonus)
    first_lag = int(ANIMALS[sp]["first_yield_day"])
    interval = int(ANIMALS[sp]["interval"])
    first_yield = 6 if sp in ("COW", "SHEEP") else 2
    recurring_yield = 4 if sp == "SHEEP" else (3 if sp == "COW" else 1)

    production_events = []
    prod_day = day + first_lag
    cand_units = {t: 0.0 for t in range(day, 29)}
    while prod_day <= 28:
        units = first_yield if prod_day == (day + first_lag) else recurring_yield
        production_events.append((prod_day, units))
        cand_units[prod_day] = float(units)
        prod_day += interval

    # Feed cost: Authoritative incremental replacement cost via PriceForecast or live spot
    feed_days = max(0, 29 - day)
    wheat_inv = market_inventory.get("WHEAT", MARKET_I0) if market_inventory else MARKET_I0
    if _PRICE_FORECAST is not None:
        feed_cost = sum(_PRICE_FORECAST.expected_price("WHEAT", t) for t in range(day, 29))
        feed_cost_model = "PriceForecast_expected_spot_replacement"
    else:
        wheat_price = float(market_price("WHEAT", wheat_inv))
        feed_cost = feed_days * wheat_price
        feed_cost_model = "live_market_spot_fallback"

    if not production_events:
        return {
            "species": sp, "day": day, "viable": False,
            "net_realized_value": -cost - feed_cost,
            "gross_product_revenue": 0.0,
            "gross_fertilizer_revenue": 0.0,
            "feed_cost": round(feed_cost, 2),
            "feed_cost_model": feed_cost_model,
            "purchase_cost": cost,
            "pasture_opportunity_cost": 0.0,
            "market_impact_cost": 0.0,
            "marginal_product_revenue": 0.0,
            "liquidation_discount": 0.0,
            "production_events": [],
            "reason": "insufficient_time_for_maturity",
        }

    # 2. Sequential Joint-Path Counterfactual Market Simulation
    exist_rate = current_count * (float(recurring_yield) / float(interval))
    base_inv = float(market_inventory.get(prod_item, MARKET_I0)) if market_inventory else float(MARKET_I0)

    known_daily_drain = TC_DEMAND.get(prod_item, 1.0) + sum(
        SHOP_DEMAND_RATES.get(prod_item, {}).get(s, 0.0) for s in (town_shops or [])
    )

    future_events = [ed for ed in UNLOCK_DAYS if day < ed <= 28]
    k = len(future_events)
    hit_rate = 12.0 if sp == "SHEEP" else 6.0
    n_hits = 1 if sp == "SHEEP" else (3 if sp == "COW" else 2)
    n_miss = 8 - n_hits
    denom = 8 ** k

    total_delta_rev = 0.0
    total_cand_rev = 0.0
    opp_supply_dict = opponent_committed_supply or {}

    # Enumerate all 2^k joint future shop paths (at most 256 paths)
    for seq in itertools.product([0, 1], repeat=k):
        # Exact integer probability representation
        hits = sum(seq)
        misses = k - hits
        path_num = (n_hits ** hits) * (n_miss ** misses)
        prob = path_num / float(denom)

        inv_without = base_inv
        inv_with = base_inv
        rev_without = 0.0
        rev_with = 0.0
        cand_rev = 0.0

        for t in range(day, 29):
            # Same future unlock path applies consistently across every day
            drain = known_daily_drain + sum(
                seq[j] * hit_rate for j, ed in enumerate(future_events) if ed <= t
            )

            opp_s = float(opp_supply_dict.get(t, 0.0))
            s_without = exist_rate
            s_with = exist_rate + cand_units[t]
            tot_s_without = s_without + opp_s
            tot_s_with = s_with + opp_s

            # Engine order of operations:
            # 1. Selling: Units enter market at beginning-of-day inventory.
            # Opponent supply depresses the effective market price curve equally for both branches.
            p_without = float(market_price(prod_item, inv_without + tot_s_without / 2.0)) if tot_s_without > 0 else float(market_price(prod_item, inv_without))
            p_with = float(market_price(prod_item, inv_with + tot_s_with / 2.0)) if tot_s_with > 0 else float(market_price(prod_item, inv_with))

            # Our farm only earns revenue on our own units
            rev_without += s_without * p_without
            rev_with += s_with * p_with
            cand_rev += cand_units[t] * p_with

            # 2. Town consumption: subtracts drain from post-sale inventory
            inv_without = max(1.0, inv_without + tot_s_without - drain)
            inv_with = max(1.0, inv_with + tot_s_with - drain)

        total_delta_rev += prob * (rev_with - rev_without)
        total_cand_rev += prob * cand_rev

    market_impact_cost = max(0.0, total_cand_rev - total_delta_rev)

    # 3. Fertilizer Contribution & Sensitivity Audit
    fert_days = max(0, 28 - day) if sp in ("COW", "SHEEP") else 0
    fert_inv = market_inventory.get("FERTILIZER", MARKET_I0) if market_inventory else MARKET_I0
    # Simulate own fertilizer supply on market price curve
    gross_fert_rev = sum(
        float(market_price("FERTILIZER", fert_inv + i)) for i in range(fert_days)
    )

    # 4. Housing / Pasture Opportunity Cost
    pasture_opp_cost = 0.0
    if empty_pastures <= 0:
        pasture_opp_cost = 200.0 + max(0.0, float(crop_opportunity_val))

    # 5. Net Realized Value
    net_realized_val = (
        total_delta_rev
        + gross_fert_rev
        - cost
        - feed_cost
        - pasture_opp_cost
    )

    fertilizer_sensitivity = {
        "full_fertilizer": round(net_realized_val, 2),
        "half_fertilizer": round(net_realized_val - 0.5 * gross_fert_rev, 2),
        "zero_fertilizer": round(net_realized_val - gross_fert_rev, 2),
    }

    return {
        "species": sp,
        "day": day,
        "viable": bool(net_realized_val > 0),
        "net_realized_value": round(net_realized_val, 2),
        "marginal_product_revenue": round(total_delta_rev, 2),
        "gross_product_revenue": round(total_cand_rev, 2),
        "gross_fertilizer_revenue": round(gross_fert_rev, 2),
        "fertilizer_sensitivity": fertilizer_sensitivity,
        "feed_cost": round(feed_cost, 2),
        "feed_cost_model": feed_cost_model,
        "purchase_cost": cost,
        "pasture_opportunity_cost": round(pasture_opp_cost, 2),
        "market_impact_cost": round(market_impact_cost, 2),
        "liquidation_discount": 0.0,
        "production_events": production_events,
        "total_units_produced": sum(u for _, u in production_events),
        "joint_paths_evaluated": 2 ** k,
        "opponent_committed_units": round(sum(opp_supply_dict.values()), 1),
        "break_even": bool(net_realized_val > 0),
    }
