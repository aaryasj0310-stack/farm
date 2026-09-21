"""P2.1: Dynamic Strawberry Portfolio Evaluator.

Pure, isolated evaluator for deciding the dynamic strawberry allocation budget S*.
Replaces rigid static caps (16 -> 18 -> 20) with marginal-value optimization:
- Evaluates remaining attainable harvests and event-level outputs.
- Computes own-supply market-price impact using integer-rounded market_price().
- Models full calendar-day occupancy and maintenance labor (e.g. 17 daily waterings).
- Benchmarks against next-best crop alternatives (Wheat feed/market, Carrot turnover, Tomato).
- Applies sequential admission with a risk buffer, bounded non-retroactively by existing commitments.
"""
from typing import Dict, Any, Tuple
import math

try:
    from config import (
        STRAWBERRY_PLANT_DEADLINE,
        get_strawberry_cap,
        CROPS,
        PRICE_FLOOR,
    )
except ImportError:
    STRAWBERRY_PLANT_DEADLINE = 13
    PRICE_FLOOR = 1
    CROPS = {
        "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
        "WHEAT": {"seed": 10, "max_yield_day": 5, "yield": 3, "ongoing": False},
        "CARROT": {"seed": 10, "max_yield_day": 4, "yield": 2, "ongoing": False},
        "TOMATO": {"seed": 40, "first_yield_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    }

    def get_strawberry_cap(day: int, eligible: bool = True, land_purchased: Any = None) -> int:
        if not eligible:
            return 0
        if day <= 8:
            return 16
        elif day <= 12:
            return 18
        elif day == 13:
            return 20
        return 0


def _shape(func: str, x: float, T: float) -> float:
    """Mirror engine _shape function."""
    if func == "linear":
        return x / T
    elif func == "sqrt":
        return math.sqrt(max(0.0, x / T))
    elif func == "sq":
        return (x / T) ** 2
    elif func == "log":
        return math.log1p(max(0.0, x / T))
    return x / T


def _engine_market_price(product: str, inventory: float) -> int:
    """Authoritative integer-rounded price matching kaggle_environments.market_price."""
    # Market parameters
    params = {
        "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "below_func": "sqrt", "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
        "WHEAT": {"base": 30, "I0": 10000, "T": 100, "below_func": "sq", "below_target": 1.50, "above_func": "linear", "above_target": 0.70},
        "CARROT": {"base": 35, "I0": 10000, "T": 100, "below_func": "sqrt", "below_target": 0.70, "above_func": "linear", "above_target": 0.90},
        "TOMATO": {"base": 60, "I0": 10000, "T": 100, "below_func": "sqrt", "below_target": 0.70, "above_func": "linear", "above_target": 1.10},
    }
    p = params.get(product, params["STRAWBERRY"])
    base = p["base"]
    I0 = p["I0"]
    T = p["T"]
    if inventory < I0:
        amp = p["below_target"] * base / _shape(p["below_func"], T, T)
        price = base + amp * _shape(p["below_func"], I0 - inventory, T)
    else:
        amp = p["above_target"] * base / _shape(p["above_func"], T, T)
        price = base - amp * _shape(p["above_func"], inventory - I0, T)
    return max(1, int(round(price)))


def compute_next_best_crop_mv(day: int, market_inventory: Dict[str, float], shed_wheat: int = 0) -> Tuple[float, str]:
    """Calculate the expected net marginal profit of the next-best alternative crop.

    Evaluated on the exact same tile from Day 'day' to Day 29.
    Returns (mv_alt, best_crop_name).
    """
    days_left = max(0, 30 - day)
    c_action = 5.0  # shadow cost per worker action

    # 1. Wheat
    # 5-day cycle. Output: 3 units/harvest. Seed: $10. Water: 5 days. Harvest: 1 action.
    n_wheat_cycles = max(1, days_left // 5)
    i_wheat = market_inventory.get("WHEAT", 10000.0)
    spot_wheat = _engine_market_price("WHEAT", i_wheat)
    # Unit value: If shed wheat is low, avoids $25 feed purchase; otherwise market price
    wheat_unit_val = max(25.0, float(spot_wheat))
    wheat_gross = n_wheat_cycles * 3.0 * wheat_unit_val
    wheat_cost = n_wheat_cycles * (10.0 + 5 * c_action + 1 * c_action)
    mv_wheat = wheat_gross - wheat_cost

    # 2. Carrot
    # 4-day cycle. Output: 2 units/harvest. Seed: $10. Water: 4 days. Harvest: 1 action.
    n_carrot_cycles = max(1, days_left // 4)
    i_carrot = market_inventory.get("CARROT", 10000.0)
    spot_carrot = _engine_market_price("CARROT", i_carrot)
    carrot_gross = n_carrot_cycles * 2.0 * float(spot_carrot)
    carrot_cost = n_carrot_cycles * (10.0 + 4 * c_action + 1 * c_action)
    mv_carrot = carrot_gross - carrot_cost

    # 3. Tomato
    # 12-day ongoing cycle (events at ages 8, 9, 10, 11). Output ~5-6 units. Seed: $40.
    if days_left >= 12:
        i_tomato = market_inventory.get("TOMATO", 10000.0)
        spot_tomato = _engine_market_price("TOMATO", i_tomato)
        tomato_gross = 5.0 * float(spot_tomato)
        tomato_cost = 40.0 + 12 * c_action + 4 * c_action
        mv_tomato = tomato_gross - tomato_cost
    else:
        mv_tomato = -100.0

    # 4. Fallow (Empty Tile)
    mv_fallow = 0.0

    crops = [
        (mv_wheat, "WHEAT"),
        (mv_carrot, "CARROT"),
        (mv_tomato, "TOMATO"),
        (mv_fallow, "FALLOW"),
    ]
    crops.sort(key=lambda x: x[0], reverse=True)
    return crops[0]


def evaluate_marginal_strawberry(
    day: int,
    k_tile: int,
    cur_market_inv: float,
    committed_tiles: int,
    shed_stock: int = 0,
) -> float:
    """Compute the expected net marginal profit of the k-th strawberry tile."""
    # Calendar days of active maintenance from Day 'day' until decay/end of season
    # For day <= 13: active for 17 calendar days
    days_active = min(17, 30 - day)
    c_action = 5.0

    # Output: 4 scheduled production events for day <= 13
    # Average yield: 1.5 units/event with baseline fertilizer availability
    v_straw = 6.0

    # Conservative town shop consumption estimate (~12 units/day over remaining season)
    days_remaining = max(1, 30 - day)
    town_demand = min(300.0, days_remaining * 12.0)

    # Projected inventory when tile k's harvest is sold
    # Accounts for existing shed inventory + already committed tiles + candidate tiles up to k
    total_committed_units = (committed_tiles + k_tile) * v_straw
    proj_inv = max(8500.0, cur_market_inv - town_demand + total_committed_units + shed_stock)

    # Realized unit price under projected market inventory
    realized_price = _engine_market_price("STRAWBERRY", proj_inv)

    # Gross revenue
    gross_revenue = v_straw * realized_price

    # Total costs: Seed ($100) + daily watering actions + harvest/delivery actions
    maintenance_cost = 100.0 + (days_active * c_action) + (4 * c_action + 2 * c_action)

    return gross_revenue - maintenance_cost


def compute_dynamic_strawberry_cap(
    day: int,
    farm_unlocked: set,
    cur_market_inv: Dict[str, float],
    committed_strawberries: int,
    shed_strawberry: int = 0,
    shed_wheat: int = 0,
    remaining_money: float = 3000.0,
    risk_buffer: float = 15.0,
) -> Tuple[int, Dict[str, Any]]:
    """Determine the optimal dynamic strawberry cap S* for the current day.

    Returns:
        (dynamic_cap, diagnostic_record)
    """
    if day > STRAWBERRY_PLANT_DEADLINE or "NE" not in farm_unlocked:
        return 0, {
            "admitted_cap": 0,
            "reason": "deadline_passed_or_ne_locked",
            "mv_alt": 0.0,
            "best_alt": "NONE",
            "marginal_values": [],
        }

    baseline_cap = get_strawberry_cap(day, True)
    if baseline_cap <= 0:
        return 0, {
            "admitted_cap": 0,
            "reason": "baseline_cap_zero",
            "mv_alt": 0.0,
            "best_alt": "NONE",
            "marginal_values": [],
        }

    # Evaluate next-best alternative crop opportunity cost
    mv_alt, best_alt = compute_next_best_crop_mv(day, cur_market_inv, shed_wheat)

    straw_mkt_inv = cur_market_inv.get("STRAWBERRY", 10000.0)

    admitted_count = 0
    mv_records = []

    # Evaluate sequentially for candidate tiles 1 .. baseline_cap
    for k in range(1, baseline_cap + 1):
        mv_straw = evaluate_marginal_strawberry(
            day=day,
            k_tile=k,
            cur_market_inv=straw_mkt_inv,
            committed_tiles=0,  # evaluate portfolio depth from 1 to k
            shed_stock=shed_strawberry,
        )
        mv_records.append({
            "k": k,
            "mv_straw": mv_straw,
            "mv_alt": mv_alt,
            "net_surplus": mv_straw - mv_alt,
        })

        if mv_straw >= mv_alt + risk_buffer:
            admitted_count = k
        else:
            # Diminishing marginal returns: stop once surplus falls below risk buffer
            break

    # Non-retroactive guarantee:
    # Cannot unplant existing strawberries, but strictly caps any new plantings
    final_cap = max(committed_strawberries, admitted_count)
    final_cap = min(final_cap, baseline_cap)

    diag = {
        "day": day,
        "baseline_cap": baseline_cap,
        "admitted_cap": final_cap,
        "committed_strawberries": committed_strawberries,
        "new_tiles_allowed": max(0, final_cap - committed_strawberries),
        "mv_alt": mv_alt,
        "best_alt": best_alt,
        "market_strawberry_inv": straw_mkt_inv,
        "marginal_evaluations": mv_records[:admitted_count + 2],
    }

    return final_cap, diag
