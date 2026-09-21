"""P2.0: Dynamic Second Melon Tranche Evaluator.

Authoritative decision engine for admitting a controlled second melon tranche
on Days 10-12 on the 2-quadrant core farm (NW + NE).

Evaluates:
  1. Timing & season horizon (strictly Days 10-12).
  2. Existing melon commitment (live tiles, planned, shed/worker inventory, sold).
  3. Endogenous market headroom & quadratic price impact.
  4. Seed capital & strict treasury solvency.
  5. Core labor serviceability & watering headroom.
  6. Opportunity cost against next-best tile alternatives (Carrot/Wheat).
  7. Dynamic sizing across candidate tranche sizes k in {0, 4, 6, 8, 10}.
"""
from typing import Dict, Any, List, Tuple, Optional
import math

try:
    from config import (
        CROPS,
        MARKET_I0,
        get_p20_second_melon_tranche_enabled,
    )
    from strategy.baked_economics import (
        MONEY_RESERVE,
        CROP_ECONOMICS,
    )
except ImportError:
    try:
        from agent.config import (
            CROPS,
            MARKET_I0,
            get_p20_second_melon_tranche_enabled,
        )
        from agent.strategy.baked_economics import (
            MONEY_RESERVE,
            CROP_ECONOMICS,
        )
    except ImportError:
        from baked_economics import (
            MONEY_RESERVE,
            CROP_ECONOMICS,
        )

# Authoritative market parameters for MELON
MELON_BASE_PRICE = 250.0
MELON_T = 300.0
MELON_ABOVE_TARGET = 3.60
MELON_SEED_COST = 80.0
MELON_UNITS_PER_TILE = 6  # optimal watering yield
MELON_MAX_CUMULATIVE_VOLUME = 140  # protect against quadratic cliff past 150-160
MELON_MIN_REALIZED_PRICE = 140.0   # minimum acceptable average selling price


def _melon_market_price(inventory: float) -> float:
    """Exact engine price for Melon at given inventory."""
    diff = inventory - MARKET_I0
    if diff <= 0:
        # Scarcity: log curve, below_target 0.20
        amp = 0.20 * MELON_BASE_PRICE / math.log(1.0 + MELON_T)
        p = MELON_BASE_PRICE + amp * math.log(1.0 + abs(diff))
    else:
        # Glut: sq curve, above_target 3.60
        amp = MELON_ABOVE_TARGET * MELON_BASE_PRICE / (MELON_T ** 2)
        p = MELON_BASE_PRICE - amp * (diff ** 2)
    return max(1.0, float(round(p)))


def _project_melon_batch_revenue(start_inv: float, units: int) -> Tuple[float, float]:
    """Calculate total revenue and average price for selling `units` melons starting from `start_inv`."""
    if units <= 0:
        return 0.0, 0.0
    total_rev = 0.0
    for u in range(1, units + 1):
        price_at_u = _melon_market_price(start_inv + u)
        total_rev += price_at_u
    avg_price = total_rev / float(units)
    return total_rev, avg_price


def evaluate_second_melon_tranche(
    day: int,
    hour: int,
    farm: Any,
    private: Any,
    market: Any,
    forecast: Any,
    committed_counts: Dict[str, int],
    empty_tiles: List[Tuple[int, int]],
    available_money: float,
    hires_today: int = 0,
    opp_advice: Any = None,
) -> Tuple[int, Dict[str, Any]]:
    """Evaluate whether to admit a second melon tranche and determine its optimal size.

    Returns:
        (selected_k, diagnostics_dict)
    """
    diag: Dict[str, Any] = {
        "enabled": bool(get_p20_second_melon_tranche_enabled()),
        "day": int(day),
        "hour": int(hour),
        "evaluated_candidates": {},
        "selected_k": 0,
        "decision_reason": "none",
    }

    if not diag["enabled"]:
        diag["decision_reason"] = "p20_disabled"
        return 0, diag

    # Gate 1: Timing
    if not (10 <= day <= 12):
        diag["decision_reason"] = f"outside_window_day_{day}"
        return 0, diag

    if day == 12 and hour >= 18:
        diag["decision_reason"] = "late_day_12_cutoff"
        return 0, diag

    # Gate 2: Usable empty core tiles
    usable_empty = [
        pos for pos in empty_tiles
        if hasattr(farm, "quadrant_of") and farm.quadrant_of(pos) in ("NW", "NE")
        and pos not in ((4, 4), (4, 5))
    ]
    if not usable_empty:
        diag["decision_reason"] = "no_usable_empty_tiles"
        return 0, diag

    # Gate 3: Existing melon commitments & volume
    live_melons = committed_counts.get("MELON", 0)
    owned_seeds = int((getattr(private, "seeds", {}) or {}).get("MELON", 0)) if private else 0
    shed_melons = int((getattr(private, "shed", {}) or {}).get("MELON", 0)) if private else 0
    worker_melons = 0
    if private and hasattr(private, "inventories"):
        for inv in private.inventories:
            worker_melons += int((inv or {}).get("MELON", 0))

    market_melon_inv = float(
        getattr(market, "inventory", {}).get("MELON", MARKET_I0)
        if hasattr(market, "inventory")
        else (market.get("inventory", {}).get("MELON", MARKET_I0) if isinstance(market, dict) else MARKET_I0)
    )

    # Estimate melons already sold: market inventory delta plus town center drain (1/day)
    approx_sold = max(0, int(market_melon_inv - MARKET_I0 + day))
    committed_volume = (live_melons * MELON_UNITS_PER_TILE) + shed_melons + worker_melons + approx_sold

    diag["existing_commitment"] = {
        "live_melons": live_melons,
        "owned_seeds": owned_seeds,
        "held_melons": shed_melons + worker_melons,
        "approx_sold": approx_sold,
        "committed_volume": committed_volume,
        "market_inventory": market_melon_inv,
    }

    if committed_volume >= MELON_MAX_CUMULATIVE_VOLUME:
        diag["decision_reason"] = f"volume_cap_saturated_{committed_volume}"
        return 0, diag

    # Gate 4: Labor & Core Farm Health Check
    unwatered_crops = 0
    total_live_crops = 0
    mature_awaiting_harvest = 0
    if farm is not None and hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if getattr(t, "is_plant", False):
                total_live_crops += 1
                if getattr(t, "consecutive_unwatered", 0) > 0 or not getattr(t, "watered_today", False):
                    unwatered_crops += 1
                if getattr(t, "yield_units", 0) > 0:
                    mature_awaiting_harvest += 1

    total_workers = 1 + (len(farm.hands) if hasattr(farm, "hands") else hires_today)
    total_daily_actions = total_workers * 24

    diag["labor_health"] = {
        "unwatered_crops": unwatered_crops,
        "total_live_crops": total_live_crops,
        "mature_awaiting_harvest": mature_awaiting_harvest,
        "total_workers": total_workers,
        "total_daily_actions": total_daily_actions,
    }

    # If unwatered crops at end of previous day was critical, protect core farm first
    if unwatered_crops > 6 and hour > 6:
        diag["decision_reason"] = f"core_labor_debt_unwatered_{unwatered_crops}"
        return 0, diag

    # Gate 5: Candidate Tranche Evaluation
    # Candidate set: k in {0, 4, 6, 8, 10}
    max_k_possible = min(len(usable_empty), 10)
    candidates = [k for k in (4, 6, 8, 10) if k <= max_k_possible]
    if not candidates:
        diag["decision_reason"] = f"insufficient_empty_tiles_{len(usable_empty)}"
        return 0, diag

    best_k = 0
    best_inc_val = 0.0

    # Next-best alternative value per tile over the 10-day melon growth window:
    # In 10 days, a tile can run 2 cycles of Carrot (8 days) or 2 cycles of Wheat (10 days).
    # Carrot: 2 cycles * 3 yield * $35 = $210 gross - $40 seed = $170 net.
    # Wheat:  2 cycles * 4 yield * $25 = $200 gross - $20 seed = $180 net.
    # We conservatively benchmark opportunity cost at $175.00 per tile.
    OPPORTUNITY_COST_PER_TILE = 175.0

    for k in candidates:
        projected_units = k * MELON_UNITS_PER_TILE
        new_total_volume = committed_volume + projected_units

        # Reject if total volume exceeds quadratic safety boundary
        if new_total_volume > MELON_MAX_CUMULATIVE_VOLUME + 12:
            diag["evaluated_candidates"][k] = {
                "feasible": False,
                "reason": f"volume_exceeds_cap_{new_total_volume}",
            }
            continue

        # Revenue projection
        tot_rev, avg_price = _project_melon_batch_revenue(market_melon_inv, projected_units)

        # Price floor check
        if avg_price < MELON_MIN_REALIZED_PRICE:
            diag["evaluated_candidates"][k] = {
                "feasible": False,
                "reason": f"price_too_low_{avg_price:.1f}",
                "avg_price": avg_price,
            }
            continue

        # Seed capital check
        needed_seeds = max(0, k - owned_seeds)
        seed_spend = needed_seeds * MELON_SEED_COST
        if available_money < seed_spend:
            diag["evaluated_candidates"][k] = {
                "feasible": False,
                "reason": f"insufficient_funds_{available_money:.1f}_needed_{seed_spend:.1f}",
            }
            continue

        # Net profit & opportunity cost
        net_melon_profit = tot_rev - seed_spend
        alt_opportunity_cost = k * OPPORTUNITY_COST_PER_TILE
        incremental_value = net_melon_profit - alt_opportunity_cost

        diag["evaluated_candidates"][k] = {
            "feasible": True,
            "projected_units": projected_units,
            "expected_revenue": tot_rev,
            "avg_price": avg_price,
            "seed_spend": seed_spend,
            "net_melon_profit": net_melon_profit,
            "alt_opportunity_cost": alt_opportunity_cost,
            "incremental_value": incremental_value,
        }

        if incremental_value > best_inc_val:
            best_inc_val = incremental_value
            best_k = k

    diag["selected_k"] = best_k
    if best_k > 0:
        diag["decision_reason"] = f"admitted_tranche_{best_k}_inc_val_{best_inc_val:.0f}"
    else:
        diag["decision_reason"] = "no_candidate_cleared_incremental_value"

    return best_k, diag
