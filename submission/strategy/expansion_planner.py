"""v5.11: Expansion Planner — deadline-aware land valuation, dynamic ROI,
treasury protection, seed pre-purchase, and crop-eligibility-driven urgency.

Sits between MacroPlanner and OrderBuilder. Connects capital → land → seed →
production → revenue as one integrated strategic loop.

Core invariants:
  - SW deadline (Day 13) is STATIC and absolute — never re-derived.
  - Treasury safety is NON-NEGOTIABLE — high urgency triggers treasury
    hoarding, NOT a looser purchase gate.
  - Pre-buy seeds only from surplus AFTER current production is funded.
  - Expansion tranche is a priority layer inside existing plant_queue,
    not a competing planting system.
  - Land decision = economic ROI + time-window urgency + treasury feasibility.
"""
import math
from config import (
    CROPS,
    LAND_ORDER,
    LAND_PRICES,
    QUADRANT_UNLOCK_DAYS,
    QUADRANT_MONEY_THRESHOLDS,
    QUADRANT_HARD_BLOCK,
    SEASON_DAYS,
    STRAWBERRY_PLANT_DEADLINE,
    MELON_PLANT_DEADLINE,
    PRE_BUY_LEAD_DAYS,
    SW_SEED_TARGETS,
    NE_SEED_TARGETS,
    SW_TREASURY_SEED_COST,
    FEED_WHEAT_BUFFER_DAYS,
    MONEY_RESERVE_DEFAULT,
    MARKET_I0,
    CROP_TILE_CAPS,
    get_sw_seed_targets,
    get_strawberry_cap,
    NE_EARLY_UNLOCK_MAX_DAY,
    NE_EARLY_UNLOCK_THRESHOLD_DAY3_5,
    NE_EARLY_UNLOCK_THRESHOLD_DAY6,
)
from strategy.baked_economics import CROP_ECONOMICS, CROP_CYCLE_LEN


# ---------------------------------------------------------------------------
# Deadline helpers
# ---------------------------------------------------------------------------

def days_to_crop_deadline(crop, current_day):
    """Days remaining until the crop's planting deadline passes.

    Returns positive if still valid, zero/negative if deadline passed.
    Uses static deadlines — no recomputation from crop params.
    """
    if crop == "STRAWBERRY":
        return STRAWBERRY_PLANT_DEADLINE - current_day
    if crop == "MELON":
        return MELON_PLANT_DEADLINE - current_day
    # One-time crops: deadline = 29 - max_yield_day
    cd = CROPS[crop]
    if cd["ongoing"]:
        last_harvest = cd["first_yield_day"] + (cd["max_yield"] - 1) * cd["interval"]
    else:
        last_harvest = cd["max_yield_day"]
    return (SEASON_DAYS - 1) - last_harvest - current_day


def expansion_seed_targets(next_quadrant, day=None, money=None, land_cost=2000):
    """Return {crop: count} seed targets for the given quadrant.

    v6.0: For SW (Q3), strictly returns WHEAT (D9-24) or CARROT (D25-27).
    """
    if next_quadrant == 3:
        return get_sw_seed_targets(day if day is not None else 9, money, land_cost)
    if next_quadrant == 2:
        return dict(NE_SEED_TARGETS)
    return {}


# ---------------------------------------------------------------------------
# Dynamic land ROI estimation (Marginal Profit Formulation)
# ---------------------------------------------------------------------------

TILES_PER_QUADRANT = 25  # 5x5 grid per quadrant


def _estimate_crop_revenue_per_tile(crop, plant_day, current_day,
                                     forecast, n_own_tiles=0, n_opp_tiles=0):
    """Estimate expected net profit per tile for a crop planted on plant_day.

    Uses the crop's harvest schedule and expected market prices from PriceForecast.
    Accurately accounts for seed costs and fertilizer applications per cycle.
    Returns (net_profit, total_units).
    """
    cd = CROPS[crop]
    econ = CROP_ECONOMICS[crop]
    fert_apps = econ.get("apps", 0)
    fert_cost_per_app = 25.0
    fert_cost_per_cycle = fert_apps * fert_cost_per_app
    seed_cost_per_cycle = cd["seed"]

    total_net = 0.0
    total_units = 0

    if cd["ongoing"]:
        # Ongoing crop (Tomato, Strawberry): planted once, harvested up to max_yield times
        h_days = []
        d = plant_day + cd["first_yield_day"]
        for _ in range(cd["max_yield"]):
            if d <= 29:
                h_days.append(d)
            d += cd["interval"]

        future_harvests = [h for h in h_days if h >= current_day]
        if not future_harvests:
            return 0.0, 0

        # Fertilized ongoing crops yield 2 units per harvest (1 unit unfertilized)
        units_per_harvest = 2 if fert_apps > 0 else 1
        gross_revenue = 0.0
        for h in future_harvests:
            price = forecast.expected_price(crop, h)
            gross_revenue += units_per_harvest * price
            total_units += units_per_harvest

        # Deduct seed and fertilizer cost once for the ongoing crop lifecycle
        net_profit = gross_revenue - seed_cost_per_cycle - fert_cost_per_cycle
        return net_profit, total_units

    else:
        # One-time crop (Wheat, Carrot, Melon): replanted across remaining season
        cycle_len = CROP_CYCLE_LEN[crop]
        cycle_start = plant_day
        units_per_harvest = cd["max_yield"]

        while cycle_start <= 25 and cycle_start + cd["max_yield_day"] <= 29:
            harvest_day = cycle_start + cd["max_yield_day"]
            if harvest_day >= current_day:
                price = forecast.expected_price(crop, harvest_day)
                rev = units_per_harvest * price
                cycle_cost = seed_cost_per_cycle + fert_cost_per_cycle
                total_net += (rev - cycle_cost)
                total_units += units_per_harvest
            cycle_start += cycle_len

        return total_net, total_units


def _allocate_portfolio_profit(n_tiles, current_day, forecast, strawberry_eligible=False, is_sw_available=None):
    """Greedy portfolio profit allocation for a set of tiles.

    Returns (total_expected_profit, allocation_dict).
    Respects CROP_TILE_CAPS and dynamic strawberry caps.
    """
    if is_sw_available is not None:
        strawberry_eligible = is_sw_available

    if n_tiles <= 0 or current_day > 25:
        return 0.0, {}

    scored_crops = []
    for crop in CROPS:
        if not _crop_allowed_quick(crop, current_day):
            continue
        net_profit, _ = _estimate_crop_revenue_per_tile(
            crop, current_day, current_day, forecast)
        if net_profit <= 0:
            continue

        if crop == "STRAWBERRY":
            cap = get_strawberry_cap(current_day, strawberry_eligible=strawberry_eligible)
        else:
            cap = CROP_TILE_CAPS.get(crop, 99)

        if cap > 0:
            scored_crops.append((crop, net_profit, cap))

    # Sort crops by expected net profit per tile (highest first)
    scored_crops.sort(key=lambda x: -x[1])

    remaining_tiles = n_tiles
    total_profit = 0.0
    allocation = {}

    for crop, profit_per_tile, cap in scored_crops:
        alloc = min(remaining_tiles, cap)
        if alloc > 0:
            allocation[crop] = alloc
            total_profit += alloc * profit_per_tile
            remaining_tiles -= alloc
        if remaining_tiles <= 0:
            break

    return total_profit, allocation


def _candidate_crop_mix_for_quadrant(next_quadrant, current_day, forecast,
                                      n_tiles=TILES_PER_QUADRANT, n_own_tiles=0, n_opp_tiles=0):
    """Generate candidate crop mixes for a quadrant.

    Returns list of (mix_dict, avg_revenue_per_tile, total_revenue).
    """
    strawberry_eligible = (next_quadrant in (2, 3))
    profit, mix = _allocate_portfolio_profit(n_tiles, current_day, forecast, strawberry_eligible=strawberry_eligible)
    if not mix or profit <= 0:
        return []
    avg_rev = profit / max(1, sum(mix.values()))
    return [(mix, avg_rev, profit)]


def _crop_allowed_quick(crop, day):
    """Fast crop eligibility check without importing macro_planner."""
    if day > 25:
        return False
    cd = CROPS[crop]
    if cd["ongoing"]:
        last_harvest = cd["first_yield_day"] + (cd["max_yield"] - 1) * cd["interval"]
    else:
        last_harvest = cd["max_yield_day"]
    if day + last_harvest > 29:
        return False
    if crop == "STRAWBERRY":
        return day <= STRAWBERRY_PLANT_DEADLINE  # Day 13
    if crop == "MELON":
        return day <= MELON_PLANT_DEADLINE  # Day 17
    return True


def evaluate_sw_timing(current_day, forecast, n_tiles=TILES_PER_QUADRANT):
    """Compare buying SW today vs waiting 1 day.

    Estimates:
      1. buy_today_value: expected profit from allocating SW tiles on current_day
      2. wait_1_day_value: expected profit from allocating SW tiles on current_day + 1
      3. delay_value: opportunity cost lost by delaying purchase by 1 day (buy_today_value - wait_1_day_value)

    Returns (buy_today_value, wait_1_day_value, delay_value, details).
    """
    buy_today_val, mix_today = _allocate_portfolio_profit(
        n_tiles, current_day, forecast, is_sw_available=True)

    wait_1_day_val, mix_tomorrow = _allocate_portfolio_profit(
        n_tiles, min(29, current_day + 1), forecast, is_sw_available=True)

    delay_val = max(0.0, buy_today_val - wait_1_day_val)

    details = {
        "current_day": current_day,
        "buy_today_value": round(buy_today_val, 1),
        "wait_1_day_value": round(wait_1_day_val, 1),
        "delay_value": round(delay_val, 1),
        "mix_today": mix_today,
        "mix_tomorrow": mix_tomorrow,
        "strawberry_tiles_today": mix_today.get("STRAWBERRY", 0),
        "strawberry_tiles_tomorrow": mix_tomorrow.get("STRAWBERRY", 0),
    }
    return buy_today_val, wait_1_day_val, delay_val, details


def get_effective_quadrant_unlock_day(next_quadrant: int) -> int:
    """Return the authoritative unlock day for a quadrant."""
    if next_quadrant not in QUADRANT_UNLOCK_DAYS:
        return 999
    unlock_day = QUADRANT_UNLOCK_DAYS[next_quadrant]
    if next_quadrant == 3:
        try:
            from config import SW_OWNERSHIP_MODE, SW_DELAYED_UNLOCK_DAY
            if SW_OWNERSHIP_MODE in ("early_liquidity", "pure_economic"):
                unlock_day = 7
            else:
                unlock_day = 9
            if SW_DELAYED_UNLOCK_DAY is not None:
                unlock_day = max(unlock_day, SW_DELAYED_UNLOCK_DAY)
        except Exception:
            unlock_day = 9
    return unlock_day


def compute_land_roi(next_quadrant, current_day, money, farm, forecast,
                     n_own_tiles=0, n_opp_tiles=0):
    """Estimate marginal expected profit and ROI of buying the next quadrant today.

    Calculates:
      profit_with_new_land - profit_without_new_land - land_cost

    roi = (incremental_profit - land_cost) / land_cost
    roi > 0.0 means the incremental revenue generated by the new land exceeds
    its purchase price.
    """
    if next_quadrant not in QUADRANT_UNLOCK_DAYS:
        return 0.0, {"reason": "no_schedule"}

    try:
        from config import get_quadrant_hard_block
        _qhb = get_quadrant_hard_block()
    except Exception:
        _qhb = QUADRANT_HARD_BLOCK
    if next_quadrant in _qhb:
        return 0.0, {"reason": "hard_blocked"}

    unlock_day = get_effective_quadrant_unlock_day(next_quadrant)
    if current_day < unlock_day:
        return 0.0, {"reason": f"before_unlock_{unlock_day}"}

    n_extra = len(farm.unlocked) - 1
    if n_extra >= len(LAND_PRICES):
        return 0.0, {"reason": "all_unlocked"}
    land_price = LAND_PRICES[n_extra]

    # Time remaining for production
    days_left = 29 - current_day
    if days_left <= 0:
        return 0.0, {"reason": "season_over"}

    # Available crop tiles on current land vs expanded land
    n_curr_quadrants = len(farm.unlocked)
    total_curr_tiles = n_curr_quadrants * TILES_PER_QUADRANT
    
    occupied = 0
    if hasattr(farm, "iter_tiles"):
        occupied = sum(1 for t in farm.iter_tiles()
                       if getattr(t, "is_animal", False) or getattr(t, "kind", None) in ("COOP", "PASTURE"))

    t_without = max(0, total_curr_tiles - occupied)
    t_with = t_without + TILES_PER_QUADRANT

    # Evaluate profit without new land — strawberry requires NE ownership
    strawberry_eligible_without = ("NE" in farm.unlocked)
    profit_without, mix_without = _allocate_portfolio_profit(
        t_without, current_day, forecast, strawberry_eligible=strawberry_eligible_without)

    # Evaluate profit with new land
    strawberry_eligible_with = strawberry_eligible_without or (next_quadrant == 2)
    profit_with, mix_with = _allocate_portfolio_profit(
        t_with, current_day, forecast, strawberry_eligible=strawberry_eligible_with)

    # Incremental profit caused specifically by the additional 25 tiles
    marginal_revenue_gain = max(0.0, profit_with - profit_without)
    expected_profit = marginal_revenue_gain - land_price
    roi = expected_profit / max(1, land_price)

    # Expanded mix delta (which crops are allocated to the new tiles)
    mix_delta = {}
    for c in set(mix_with) | set(mix_without):
        d_tiles = mix_with.get(c, 0) - mix_without.get(c, 0)
        if d_tiles > 0:
            mix_delta[c] = d_tiles

    # Dynamic SW timing comparison (Buy Today vs Wait 1 Day)
    buy_today_val, wait_1_day_val, delay_val = marginal_revenue_gain, 0.0, 0.0
    sw_timing_info = {}
    if next_quadrant == 3:
        buy_today_val, wait_1_day_val, delay_val, sw_timing_info = evaluate_sw_timing(
            current_day, forecast, n_tiles=TILES_PER_QUADRANT)

    return roi, {
        "land_price": land_price,
        "profit_without_land": round(profit_without, 0),
        "profit_with_land": round(profit_with, 0),
        "marginal_revenue_gain": round(marginal_revenue_gain, 0),
        "expected_profit": round(expected_profit, 0),
        "roi": round(roi, 2),
        "best_mix": mix_delta or mix_with,
        "mix_with": mix_with,
        "mix_without": mix_without,
        "days_left": days_left,
        "t_without": t_without,
        "t_with": t_with,
        "buy_today_value": round(buy_today_val, 1),
        "wait_1_day_value": round(wait_1_day_val, 1),
        "delay_value": round(delay_val, 1),
        "sw_timing": sw_timing_info,
    }


def opportunity_window_factor(next_quadrant, current_day):
    """Time-window factor based on planting viability window.

    Returns 1.0 when the season permits profitable production,
    and 0.0 when no productive planting window remains.
    Mathematically derived from shortest crop lifecycle:
      Carrot requires 3 days (first_yield_day=2, max_yield_day=3).
      Planting on Day 26 matures on Day 26 + 3 = 29 (final season day).
      Planting on Day 27+ matures on Day 30+ (post-season, zero salvage).
    """
    if current_day > 25:
        # Planting viability cutoff: planting ceases after Day 25.
        return 0.0

    return 1.0


# ---------------------------------------------------------------------------
# Land urgency
# ---------------------------------------------------------------------------

def compute_land_urgency(next_quadrant, current_day, money, farm,
                         current_commitments=0):
    """Deadline-aware urgency for purchasing the next quadrant.

    Returns (urgency: float 0..1, reason: str, info: dict).

    Urgency is driven by days_to_deadline for the quadrant's key crop.
    High urgency triggers treasury HOARDING (cut discretionary spending),
    NOT a looser purchase gate. The purchase gate is always:
        money >= land_price + current_commitments + seed_tranche + reserve
    """
    if next_quadrant not in QUADRANT_UNLOCK_DAYS:
        return 0.0, "no_unlock_schedule", {}

    unlock_day = QUADRANT_UNLOCK_DAYS[next_quadrant]
    threshold = QUADRANT_MONEY_THRESHOLDS[next_quadrant]
    n_extra = len(farm.unlocked) - 1
    if n_extra >= len(LAND_PRICES):
        return 0.0, "all_quadrants_unlocked", {}
    land_price = LAND_PRICES[n_extra]

    # Static deadline for the quadrant's key crop / payback window
    if next_quadrant == 3:
        deadline = 11  # Rule P2: pasture/fertilizer window requires unlock by Day 11
    elif next_quadrant == 2:
        deadline = MELON_PLANT_DEADLINE  # NE is less deadline-sensitive
    else:
        deadline = SEASON_DAYS - 1

    days_to_deadline = deadline - current_day

    # Seed tranche cost for this quadrant
    targets = expansion_seed_targets(next_quadrant, current_day)
    seed_cost = sum(CROPS[c]["seed"] * n for c, n in targets.items())

    # Treasury requirement: land + seeds + feed + reserve
    treasury_requirement = land_price + seed_cost + current_commitments + MONEY_RESERVE_DEFAULT

    if current_day > deadline:
        urgency = 0.0
        reason = f"{next_quadrant}_deadline_passed"
    elif current_day < unlock_day:
        urgency = 0.1
        reason = f"before_unlock_day_{unlock_day}"
    elif days_to_deadline < 0:
        urgency = 0.0
        reason = "deadline_expired"
    elif days_to_deadline <= 2:
        urgency = 1.0
        reason = f"critical_{days_to_deadline}_days_left"
    elif days_to_deadline <= 4:
        urgency = 0.8
        reason = f"high_urgency_{days_to_deadline}_days_left"
    elif money >= treasury_requirement:
        urgency = 0.6
        reason = "treasury_ready"
    else:
        urgency = 0.3
        reason = f"building_treasury_need_{treasury_requirement - money:.0f}_more"

    return urgency, reason, {
        "unlock_day": unlock_day,
        "threshold": threshold,
        "land_price": land_price,
        "deadline": deadline,
        "days_to_deadline": days_to_deadline,
        "seed_cost": seed_cost,
        "treasury_requirement": treasury_requirement,
    }


def compute_conservative_inflows_before_hire(farm, private=None) -> float:
    """Compute conservative cash inflows from shed inventory before tomorrow morning's hiring."""
    shed = {}
    if private is not None and hasattr(private, "shed") and isinstance(private.shed, dict):
        shed = private.shed
    elif hasattr(farm, "shed") and isinstance(farm.shed, dict):
        shed = farm.shed
    elif hasattr(farm, "private") and hasattr(farm.private, "shed"):
        shed = farm.private.shed

    base_prices = {
        "MILK": 160.0, "WOOL": 200.0, "EGG": 50.0,
        "STRAWBERRY": 120.0, "MELON": 250.0, "TOMATO": 60.0,
        "CARROT": 35.0, "WHEAT": 25.0, "FERTILIZER": 100.0,
    }
    val = 0.0
    for prod, cnt in shed.items():
        if prod in base_prices and isinstance(cnt, (int, float)) and cnt > 0:
            val += cnt * base_prices[prod] * 0.8  # conservative 80% market price factor
    return val


# ---------------------------------------------------------------------------
# Purchase gate (non-negotiable treasury safety & dynamic economic gate)
# ---------------------------------------------------------------------------

def should_buy_land(next_quadrant, current_day, money, farm,
                    hire_cost=0, feed_cost=0, animal_cost=0,
                    reserve=MONEY_RESERVE_DEFAULT, roi=0.0,
                    ow_factor=1.0,
                    forecast=None, n_own_tiles=0, n_opp_tiles=0,
                    seeds_owned=None,
                    wheat_on_hand=0, projected_wheat_requirement=0,
                    actual_feed_shortfall_units=0, urgency=0.0,
                    treasury_protection_active=False,
                    is_purchase_hour=True,
                    already_committed_seed_cost=0.0,
                    private=None,
                    hour=0):
    """Determine if land should be purchased TODAY via dynamic economic gates.

    Requirements:
      1. Quadrant legally available (past unlock day, unbought, not hard blocked).
      2. Treasury covers land + mandatory commitments + seed tranche + reserve.
      3. Labor/operational capacity can service the added land.
      4. Adjusted ROI is positive and clears economic threshold.
      5. Explicit payback: expected_remaining_profit > land_price + incremental_support_costs.
    """
    if next_quadrant not in QUADRANT_UNLOCK_DAYS:
        return False, "no_schedule", {}
    try:
        from config import get_quadrant_hard_block
        _qhb = get_quadrant_hard_block()
    except Exception:
        _qhb = QUADRANT_HARD_BLOCK
    if next_quadrant in _qhb:
        return False, "hard_blocked", {}

    try:
        from config import (
            SW_OWNERSHIP_MODE,
            SW_TIMING_PRIOR_ENABLED,
            SW_SAFETY_RESERVE,
            STRATEGIC_SW_OWNERSHIP_ENABLED,
        )
    except Exception:
        SW_OWNERSHIP_MODE = "production"
        SW_TIMING_PRIOR_ENABLED = False
        SW_SAFETY_RESERVE = 300.0
        STRATEGIC_SW_OWNERSHIP_ENABLED = False

    unlock_day = get_effective_quadrant_unlock_day(next_quadrant)

    n_extra = len(farm.unlocked) - 1
    if n_extra >= len(LAND_PRICES):
        return False, "all_unlocked", {}
    land_price = LAND_PRICES[n_extra]

    if current_day < unlock_day:
        diag = {
            "day": current_day,
            "next_quadrant": next_quadrant,
            "money": round(float(money), 2),
            "land_price": land_price,
            "blocking_treasury_term": f"before_day_{unlock_day}",
            "projected_post_buy_cash": round(float(money) - land_price, 2),
            "mandatory_near_term_obligations": 0.0,
            "post_sw_cash_minus_obligations": round(float(money) - land_price, 2),
            "final_rejection_or_acceptance_reason": f"before_day_{unlock_day}",
        }
        return False, f"before_day_{unlock_day}", diag

    # Seed tranche cost — use dynamic targets if available, accounting for seeds already owned
    targets = expansion_seed_targets(next_quadrant, current_day, money)
    if seeds_owned is None:
        if hasattr(farm, "seeds"):
            seeds_owned = farm.seeds
        elif hasattr(farm, "private") and hasattr(farm.private, "seeds"):
            seeds_owned = farm.private.seeds
        else:
            seeds_owned = {}

    seed_cost = 0.0
    for c, n in targets.items():
        have = 0
        if isinstance(seeds_owned, dict):
            val = seeds_owned.get(c, 0)
            have = val if isinstance(val, (int, float)) else 0
        elif hasattr(seeds_owned, "get"):
            try:
                val = seeds_owned.get(c, 0)
                have = val if isinstance(val, (int, float)) else 0
            except Exception:
                have = 0
        diff = max(0, n - have)
        seed_cost += CROPS[c]["seed"] * diff

    # Mandatory commitments: hires + actual unavoidable survival feed shortfall
    # Discretionary planned animals are excluded from mandatory commitments before land
    planned_animal_cost = float(animal_cost)
    mandatory = float(hire_cost) + float(feed_cost)

    # Total required: land + mandatory + seed_tranche + reserve
    total_required = land_price + mandatory + seed_cost + reserve

    # Dynamic SW timing details
    buy_today_val, wait_1_day_val, delay_val = 0.0, 0.0, 0.0
    sw_timing_info = {}
    if next_quadrant == 3 and forecast is not None:
        buy_today_val, wait_1_day_val, delay_val, sw_timing_info = evaluate_sw_timing(
            current_day, forecast, n_tiles=TILES_PER_QUADRANT)

    adjusted_roi = roi * ow_factor

    # Incremental support costs and explicit payback calculation:
    incremental_support_costs = seed_cost
    expected_remaining_profit = (1.0 + roi) * land_price
    payback_surplus = expected_remaining_profit - (land_price + incremental_support_costs)

    # Operational/labor serviceability check (Fix 1: compute_projected_workers)
    try:
        from strategy.land_serviceability_model import compute_projected_workers
        worker_count = compute_projected_workers(farm, current_day, money=money, hour=hour)
    except Exception:
        worker_count = 1 + (len(farm.hands) if hasattr(farm, "hands") else 0)

    current_active_tiles = 0
    if hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if isinstance(t, dict):
                if t.get("is_plant") or t.get("is_animal") or t.get("plant") or t.get("animal"):
                    current_active_tiles += 1
            else:
                if (getattr(t, "is_plant", False) or getattr(t, "is_animal", False)) and not getattr(t, "is_fallow", False):
                    current_active_tiles += 1

    best_k = 15
    sw_serv_diag = {}
    if next_quadrant == 3:
        try:
            from strategy.land_serviceability_model import evaluate_sw_serviceability
            from config import SW_P1_PURCHASE_COMMITTED_HERD_ONLY
            labor_adequate, best_k, sw_serv_diag = evaluate_sw_serviceability(
                current_day, farm, money, forecast, target_quadrant=3,
                hour=hour, allow_hypothetical=True,
                reserve_desired_herd=not SW_P1_PURCHASE_COMMITTED_HERD_ONLY,
            )
        except Exception:
            labor_adequate = (worker_count >= 2) or (current_active_tiles < 15)
    else:
        labor_adequate = (worker_count >= 2) or (current_active_tiles < 15)

    shortfall = max(0.0, total_required - money)
    diag_base = {
        "day": current_day,
        "next_quadrant": next_quadrant,
        "money": round(float(money), 2),
        "land_price": land_price,
        "hire_cost": round(float(hire_cost), 2),
        "wheat_on_hand": int(wheat_on_hand),
        "projected_wheat_requirement": int(projected_wheat_requirement),
        "actual_feed_shortfall_units": int(actual_feed_shortfall_units),
        "actual_feed_shortfall_cost": round(float(feed_cost), 2),
        "planned_animal_cost": round(planned_animal_cost, 2),
        "seed_tranche_cost": round(seed_cost, 2),
        "reserve": round(float(reserve), 2),
        "true_mandatory_commitment": round(mandatory, 2),
        "total_required_cash": round(total_required, 2),
        "shortfall": round(shortfall, 2),
        "roi": round(roi, 4),
        "adjusted_roi": round(adjusted_roi, 4),
        "labor_serviceability_result": bool(labor_adequate),
        "sw_p1_purchase_committed_herd_only": bool(
            sw_serv_diag.get("reserve_desired_herd") is False
        ) if next_quadrant == 3 else False,
        "ne_observed_animals_and_housing": sw_serv_diag.get("ne_observed_animals_and_housing"),
        "ne_desired_sheep_target": sw_serv_diag.get("ne_desired_sheep_target"),
        "ne_reserved_sheep_workload_count": sw_serv_diag.get("ne_reserved_sheep_workload_count"),
        "sw_labor_nw_deficit": sw_serv_diag.get("nw_deficit"),
        "sw_labor_ne_deficit": sw_serv_diag.get("ne_deficit"),
        "best_k_tiles": best_k,
        "purchase_time_best_k": best_k,
        "best_k_serviceable": sw_serv_diag.get("best_k_serviceable", best_k if next_quadrant == 3 else 25),
        "serviceability_fraction": sw_serv_diag.get("serviceability_fraction", 1.0),
        "candidate_sw_workload": sw_serv_diag.get("candidate_sw_workload", 0.0),
        "estimated_travel_overhead": sw_serv_diag.get("estimated_travel_overhead", 0.0),
        "net_marginal_profit": sw_serv_diag.get("net_marginal_profit", 0.0),
        "serviceability_adjusted_roi": sw_serv_diag.get("serviceability_adjusted_roi", round(adjusted_roi, 4)),
        "expected_nw_ne_opportunity_cost": sw_serv_diag.get("expected_nw_ne_opportunity_cost", 0.0),
        "urgency": round(float(urgency), 2),
        "treasury_protection_active": bool(treasury_protection_active),
        # Legacy/helper fields preserved for backward compatibility
        "mandatory": mandatory,
        "seed_cost": seed_cost,
        "total_required": total_required,
        "ow_factor": ow_factor,
        "expected_remaining_profit": round(expected_remaining_profit, 1),
        "incremental_support_costs": round(incremental_support_costs, 1),
        "payback_surplus": round(payback_surplus, 1),
        "worker_count": worker_count,
        "current_active_tiles": current_active_tiles,
        "buy_today_value": round(buy_today_val, 1),
        "wait_1_day_value": round(wait_1_day_val, 1),
        "delay_value": round(delay_val, 1),
        "sw_timing": sw_timing_info,
    }

    # Leader heuristic: Early NE land unlock on Days 3-6 when cash >= threshold
    thresh = NE_EARLY_UNLOCK_THRESHOLD_DAY6 if current_day == 6 else NE_EARLY_UNLOCK_THRESHOLD_DAY3_5
    if next_quadrant == 2 and 3 <= current_day <= NE_EARLY_UNLOCK_MAX_DAY and money >= thresh:
        if money >= land_price + mandatory:
            reason = "early_ne_leader_unlock"
            diag = dict(diag_base)
            diag["final_rejection_or_acceptance_reason"] = reason
            return True, reason, diag

    # =========================================================================
    # Point 4.1 Late-Season Isolated SW Zonal Acreage Expansion Gate
    # =========================================================================
    try:
        from config import (
            get_p41_sw_zonal_expansion_enabled,
            P41_SW_MIN_DAY,
            P41_SW_MIN_CASH,
            P41_SW_MIN_CORE_OCCUPANCY,
            SHED_ACCESS_TILES,
        )
        p41_sw_enabled = bool(get_p41_sw_zonal_expansion_enabled())
    except Exception:
        p41_sw_enabled = False
        P41_SW_MIN_DAY = 14
        P41_SW_MIN_CASH = 15000.0
        P41_SW_MIN_CORE_OCCUPANCY = 0.90
        SHED_ACCESS_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]

    if p41_sw_enabled and next_quadrant == 3:
        core_tiles = []
        occupied_core = 0
        if hasattr(farm, "iter_tiles") and hasattr(farm, "quadrant_of"):
            for t in farm.iter_tiles():
                q = farm.quadrant_of(t.pos)
                if q in ("NW", "NE") and t.pos not in SHED_ACCESS_TILES:
                    core_tiles.append(t)
                    if (
                        getattr(t, "is_plant", False)
                        or getattr(t, "is_animal", False)
                        or getattr(t, "kind", "") in ("PASTURE", "COOP")
                    ):
                        occupied_core += 1
        core_occupancy = (occupied_core / len(core_tiles)) if core_tiles else 0.0

        diag = dict(diag_base)
        diag["p41_core_occupancy"] = round(core_occupancy, 4)
        diag["p41_worker_count"] = worker_count
        diag["p41_current_money"] = round(float(money), 2)

        if current_day < P41_SW_MIN_DAY:
            reason = f"before_day_{P41_SW_MIN_DAY}"
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

        if money < P41_SW_MIN_CASH:
            reason = f"p41_insufficient_cash_{money:.0f}_lt_{P41_SW_MIN_CASH:.0f}"
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

        if worker_count < 13:
            reason = f"p41_insufficient_workers_{worker_count}_lt_13"
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

        if core_occupancy < P41_SW_MIN_CORE_OCCUPANCY:
            reason = f"p41_core_occupancy_low_{core_occupancy:.2f}_lt_{P41_SW_MIN_CORE_OCCUPANCY:.2f}"
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

        reason = "p41_sw_zonal_authorized"
        diag["final_rejection_or_acceptance_reason"] = reason
        return True, reason, diag

    # =========================================================================
    # Authoritative Liquidity Gate for SW Ownership (Arms B, C, D)
    # =========================================================================
    is_experiment_sw = (next_quadrant == 3 and SW_OWNERSHIP_MODE in ("early_liquidity", "pure_economic"))

    if is_experiment_sw:
        # 1. Unavoidable hire commitment: today's unfinished hire + tomorrow morning's shortfall
        try:
            from config import get_target_hands
            from strategy.macro_planner import hire_total_cost
            tomorrow_hands = get_target_hands(current_day + 1)
            tomorrow_hire_cost = float(hire_total_cost(tomorrow_hands))
        except Exception:
            tomorrow_hire_cost = 54.0

        conservative_inflow = compute_conservative_inflows_before_hire(farm, private)
        tomorrow_hire_shortfall = max(0.0, tomorrow_hire_cost - conservative_inflow)
        unavoidable_hire_commitment = float(hire_cost) + tomorrow_hire_shortfall

        # 2. Unavoidable feed shortfall
        unavoidable_feed_shortfall = float(feed_cost)

        # 3. Already committed seed cost (actual obligations only, strictly excludes future SW seeds)
        committed_seed_cost = float(already_committed_seed_cost)

        # 4. Safety reserve (frozen at $300 across all arms)
        safety_reserve = float(SW_SAFETY_RESERVE)

        # 5. Mandatory near-term obligations & post-buy cash
        mandatory_near_term_obligations = unavoidable_hire_commitment + unavoidable_feed_shortfall + committed_seed_cost
        projected_post_buy_cash = float(money) - land_price
        post_sw_cash_minus_obligations = projected_post_buy_cash - mandatory_near_term_obligations
        total_required_cash = land_price + mandatory_near_term_obligations + safety_reserve

        # 6. Authoritative Treasury Safety Model Test:
        # cash - SW_cost >= unavoidable_next_hire_commitment + unavoidable_feed_shortfall + already_committed_seed_cost + safety_reserve
        if post_sw_cash_minus_obligations < safety_reserve:
            if money < land_price:
                blocking_term = "insufficient_cash_for_land"
            elif projected_post_buy_cash < unavoidable_hire_commitment:
                blocking_term = "insufficient_cash_for_hires"
            elif projected_post_buy_cash < unavoidable_hire_commitment + unavoidable_feed_shortfall:
                blocking_term = "insufficient_cash_for_feed"
            elif projected_post_buy_cash < mandatory_near_term_obligations:
                blocking_term = "insufficient_cash_for_seed_commitments"
            else:
                blocking_term = "insufficient_cash_for_safety_reserve"

            diag = dict(diag_base)
            diag["blocking_treasury_term"] = blocking_term
            diag["projected_post_buy_cash"] = round(projected_post_buy_cash, 2)
            diag["mandatory_near_term_obligations"] = round(mandatory_near_term_obligations, 2)
            diag["post_sw_cash_minus_obligations"] = round(post_sw_cash_minus_obligations, 2)
            diag["final_rejection_or_acceptance_reason"] = blocking_term
            return False, blocking_term, diag

        # 7. Labor Serviceability Check
        is_sw_serv = sw_serv_diag.get("is_serviceable", labor_adequate)
        if not (labor_adequate or is_sw_serv):
            reason = "insufficient_labor_capacity"
            diag = dict(diag_base)
            diag["blocking_treasury_term"] = None
            diag["projected_post_buy_cash"] = round(projected_post_buy_cash, 2)
            diag["mandatory_near_term_obligations"] = round(mandatory_near_term_obligations, 2)
            diag["post_sw_cash_minus_obligations"] = round(post_sw_cash_minus_obligations, 2)
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

        # 8. Clean C vs D Economic Evaluation:
        economic_value = payback_surplus
        if SW_TIMING_PRIOR_ENABLED:  # Arm C: Dusta-informed prior
            # Modest soft urgency bonus centered on Days 8-9 (peak at Day 8.5)
            timing_prior = 250.0 * math.exp(-((current_day - 8.5) ** 2) / (2.0 * (1.0 ** 2)))
            land_score = economic_value + timing_prior
            economic_ok = (land_score > 0.0) and (adjusted_roi > -0.05)
        else:  # Arm D / Arm B: Pure economics
            timing_prior = 0.0
            land_score = economic_value
            economic_ok = (adjusted_roi > 0.0) and (economic_value > 0.0)

        if not economic_ok:
            reason = f"economic_score_{land_score:.0f}_non_positive"
            diag = dict(diag_base)
            diag["blocking_treasury_term"] = None
            diag["land_score"] = round(land_score, 2)
            diag["timing_prior"] = round(timing_prior, 2)
            diag["projected_post_buy_cash"] = round(projected_post_buy_cash, 2)
            diag["mandatory_near_term_obligations"] = round(mandatory_near_term_obligations, 2)
            diag["post_sw_cash_minus_obligations"] = round(post_sw_cash_minus_obligations, 2)
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

        # All treasury safety and economic criteria cleared!
        reason = "sw_authorized_early_liquidity"
        diag = dict(diag_base)
        diag["blocking_treasury_term"] = None
        diag["land_score"] = round(land_score, 2)
        diag["timing_prior"] = round(timing_prior, 2)
        diag["projected_post_buy_cash"] = round(projected_post_buy_cash, 2)
        diag["mandatory_near_term_obligations"] = round(mandatory_near_term_obligations, 2)
        diag["post_sw_cash_minus_obligations"] = round(post_sw_cash_minus_obligations, 2)
        diag["final_rejection_or_acceptance_reason"] = reason
        return True, reason, diag

    # Legacy / Strategic SW Ownership fallback (if SW_OWNERSHIP_MODE == "production" and STRATEGIC_SW_OWNERSHIP_ENABLED)
    if STRATEGIC_SW_OWNERSHIP_ENABLED and next_quadrant == 3 and 9 <= current_day <= 14:
        mandatory_commitments = float(hire_cost) + float(feed_cost) + float(seed_cost) + float(planned_animal_cost) + 150.0
        cash_after_land = money - land_price
        if cash_after_land < mandatory_commitments:
            shortfall = mandatory_commitments - cash_after_land
            reason = f"strategic_sw_liquidity_short_{shortfall:.0f}"
            diag = dict(diag_base)
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

        is_sw_serv = sw_serv_diag.get("is_serviceable", labor_adequate)
        if labor_adequate or is_sw_serv:
            reason = "strategic_sw_ownership_cleared"
            diag = dict(diag_base)
            diag["final_rejection_or_acceptance_reason"] = reason
            return True, reason, diag
        else:
            reason = "insufficient_labor_capacity"
            diag = dict(diag_base)
            diag["final_rejection_or_acceptance_reason"] = reason
            return False, reason, diag

    # Standard Production Policy (Arm A)
    # 1. Adjusted ROI must clear threshold (> 0.0)
    if adjusted_roi <= 0:
        reason = f"adjusted_roi_{adjusted_roi:.2f}_non_positive"
        diag = dict(diag_base)
        diag["final_rejection_or_acceptance_reason"] = reason
        return False, reason, diag

    # 2. Economic payback test:
    if payback_surplus <= 0:
        reason = f"insufficient_payback_{payback_surplus:.0f}"
        diag = dict(diag_base)
        diag["final_rejection_or_acceptance_reason"] = reason
        return False, reason, diag

    # 3. Treasury safety gate
    if money < total_required:
        reason = f"short_{shortfall:.0f}"
        diag = dict(diag_base)
        diag["final_rejection_or_acceptance_reason"] = reason
        return False, reason, diag

    # 4. Labor serviceability check
    if not labor_adequate:
        reason = "insufficient_labor_capacity"
        diag = dict(diag_base)
        diag["final_rejection_or_acceptance_reason"] = reason
        return False, reason, diag

    reason = "treasury_sufficient_roi_positive"
    diag = dict(diag_base)
    diag["final_rejection_or_acceptance_reason"] = reason
    return True, reason, diag


# ---------------------------------------------------------------------------
# Seed pre-purchase (from surplus only)
# ---------------------------------------------------------------------------

def compute_pre_buy_seeds(next_quadrant, current_day, surplus_money):
    """Compute seeds to pre-buy for a future land unlock.

    Only purchases from SURPLUS after all current production is funded.
    If surplus is zero, returns empty dict (seeds wait until unlock day).
    """
    if next_quadrant not in QUADRANT_UNLOCK_DAYS:
        return {}
    unlock_day = QUADRANT_UNLOCK_DAYS[next_quadrant]
    if current_day != unlock_day - PRE_BUY_LEAD_DAYS:
        return {}  # only pre-buy on the exact lead day

    targets = expansion_seed_targets(next_quadrant)
    result = {}
    remaining = surplus_money

    for crop, target_n in targets.items():
        unit_cost = CROPS[crop]["seed"]
        # Buy as many as surplus allows, up to target
        affordable = min(target_n, int(remaining // unit_cost))
        if affordable > 0:
            result[crop] = affordable
            remaining -= affordable * unit_cost

    return result


# ---------------------------------------------------------------------------
# Expansion crop priority (for injection into Phase 2b scoring loop)
# ---------------------------------------------------------------------------

def expansion_crop_priorities(next_quadrant, current_day):
    """Return {crop: priority_bias} for the expansion tranche.

    v6.0: For SW (Q3), strictly biases WHEAT (D9-24) and CARROT (D25-27).
    Higher priority_bias means this crop should be preferred on
    expansion tiles.
    """
    if next_quadrant == 3:
        if current_day <= 24:
            return {"WHEAT": 100.0}
        elif current_day <= 27:
            return {"CARROT": 100.0}
        return {}

    if current_day > STRAWBERRY_PLANT_DEADLINE:
        return {}  # no priority after deadline

    targets = expansion_seed_targets(next_quadrant, current_day)
    priorities = {}
    for crop, count in targets.items():
        dt = days_to_crop_deadline(crop, current_day)
        if dt <= 2:
            priorities[crop] = 100.0  # critical — override scoring
        elif dt <= 4:
            priorities[crop] = 50.0   # high — strong bias
        else:
            priorities[crop] = 10.0   # moderate — mild bias

    return priorities
