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

    v5.11: If day and money are provided, use dynamic targets for SW.
    Otherwise, fall back to static targets for backward compatibility.
    """
    if next_quadrant == 3 and day is not None and money is not None:
        return get_sw_seed_targets(day, money, land_cost)
    if next_quadrant == 3:
        return dict(SW_SEED_TARGETS)
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


def _allocate_portfolio_profit(n_tiles, current_day, forecast, is_sw_available=False):
    """Heuristically allocate up to n_tiles among eligible crops to maximize profit.

    Returns (total_expected_profit, allocation_dict).
    Respects CROP_TILE_CAPS and dynamic strawberry caps.
    """
    if n_tiles <= 0 or current_day > 25:
        return 0.0, {}

    from config import get_strawberry_cap

    scored_crops = []
    for crop in CROPS:
        if not _crop_allowed_quick(crop, current_day):
            continue
        net_profit, _ = _estimate_crop_revenue_per_tile(
            crop, current_day, current_day, forecast)
        if net_profit <= 0:
            continue

        if crop == "STRAWBERRY":
            cap = get_strawberry_cap(current_day, is_sw_available)
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
    is_sw = (next_quadrant == 3)
    profit, mix = _allocate_portfolio_profit(n_tiles, current_day, forecast, is_sw_available=is_sw)
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

    unlock_day = QUADRANT_UNLOCK_DAYS[next_quadrant]
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

    # Evaluate profit without new land
    is_sw_curr = ("SW" in farm.unlocked)
    profit_without, mix_without = _allocate_portfolio_profit(
        t_without, current_day, forecast, is_sw_available=is_sw_curr)

    # Evaluate profit with new land
    is_sw_with = is_sw_curr or (next_quadrant == 3)
    profit_with, mix_with = _allocate_portfolio_profit(
        t_with, current_day, forecast, is_sw_available=is_sw_with)

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
    """
    if current_day > 25:
        return 0.0  # planting stops after Day 25

    if next_quadrant == 3:
        # SW primary crop is Strawberry (deadline Day 13)
        # When current_day <= 13, window is fully open.
        # After Day 13, Strawberry cap becomes 0, but other crops (Tomato, Carrot)
        # can still be evaluated cleanly by compute_land_roi.
        return 1.0
    elif next_quadrant == 2:
        return 1.0

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

    # Static deadline for the quadrant's key crop
    if next_quadrant == 3:
        deadline = STRAWBERRY_PLANT_DEADLINE
    elif next_quadrant == 2:
        deadline = MELON_PLANT_DEADLINE  # NE is less deadline-sensitive
    else:
        deadline = SEASON_DAYS - 1

    days_to_deadline = deadline - current_day

    # Seed tranche cost for this quadrant
    targets = expansion_seed_targets(next_quadrant)
    seed_cost = sum(CROPS[c]["seed"] * n for c, n in targets.items())

    # Treasury requirement: land + seeds + feed + reserve
    treasury_requirement = land_price + seed_cost + current_commitments + MONEY_RESERVE_DEFAULT

    if current_day > deadline:
        urgency = 0.0
        reason = f"{next_quadrant}_deadline_passed"
    elif current_day < unlock_day:
        urgency = 0.1
        reason = f"before_unlock_day_{unlock_day}"
    elif days_to_deadline <= 0:
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


# ---------------------------------------------------------------------------
# Purchase gate (non-negotiable treasury safety)
# ---------------------------------------------------------------------------

def should_buy_land(next_quadrant, current_day, money, farm,
                    hire_cost=0, feed_cost=0, animal_cost=0,
                    reserve=MONEY_RESERVE_DEFAULT, roi=0.0,
                    ow_factor=1.0,
                    forecast=None, n_own_tiles=0, n_opp_tiles=0):
    """Determine if land should be purchased TODAY.

    The gate requires:
      1. Past unlock day
      2. Money covers land + mandatory commitments + seed tranche + reserve
      3. adjusted_roi > 0 (land + timing is economically justified)

    v5.11: adjusted_roi = roi × ow_factor
    If adjusted_roi <= 0, DO NOT BUY regardless of treasury.

    High urgency does NOT loosen the gate. It only triggers treasury hoarding
    in the macro planner's budget chain.
    """
    if next_quadrant not in QUADRANT_UNLOCK_DAYS:
        return False, "no_schedule", {}
    if next_quadrant in QUADRANT_HARD_BLOCK:
        return False, "hard_blocked", {}

    unlock_day = QUADRANT_UNLOCK_DAYS[next_quadrant]
    if current_day < unlock_day:
        return False, f"before_day_{unlock_day}", {}

    n_extra = len(farm.unlocked) - 1
    if n_extra >= len(LAND_PRICES):
        return False, "all_unlocked", {}
    land_price = LAND_PRICES[n_extra]

    # Seed tranche cost — use dynamic targets if available
    targets = expansion_seed_targets(next_quadrant, current_day, money)
    seed_cost = sum(CROPS[c]["seed"] * n for c, n in targets.items())

    # Mandatory commitments: hires + feed + seeds for current production
    mandatory = hire_cost + feed_cost + animal_cost

    # Total required: land + mandatory + seed_tranche + reserve
    total_required = land_price + mandatory + seed_cost + reserve

    # Dynamic SW timing details
    buy_today_val, wait_1_day_val, delay_val = 0.0, 0.0, 0.0
    sw_timing_info = {}
    if next_quadrant == 3 and forecast is not None:
        buy_today_val, wait_1_day_val, delay_val, sw_timing_info = evaluate_sw_timing(
            current_day, forecast, n_tiles=TILES_PER_QUADRANT)

    adjusted_roi = roi * ow_factor

    diag_base = {
        "land_price": land_price,
        "mandatory": mandatory,
        "seed_cost": seed_cost,
        "reserve": reserve,
        "total_required": total_required,
        "roi": roi,
        "ow_factor": ow_factor,
        "adjusted_roi": adjusted_roi,
        "buy_today_value": round(buy_today_val, 1),
        "wait_1_day_value": round(wait_1_day_val, 1),
        "delay_value": round(delay_val, 1),
        "sw_timing": sw_timing_info,
    }

    # v5.11: STRICT GATE — adjusted_roi must be positive to buy
    if adjusted_roi <= 0:
        return False, f"adjusted_roi_{adjusted_roi:.2f}_non_positive", diag_base

    if money >= total_required:
        return True, "treasury_sufficient_roi_positive", diag_base
    else:
        shortfall = total_required - money
        diag = dict(diag_base)
        diag["shortfall"] = shortfall
        return False, f"short_{shortfall:.0f}", diag


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

    Higher priority_bias means this crop should be preferred on
    expansion tiles. The existing _crop_score still runs — this just
    biases the scoring in favor of deadline-critical crops.
    """
    if current_day > STRAWBERRY_PLANT_DEADLINE:
        return {}  # no priority after deadline

    targets = expansion_seed_targets(next_quadrant)
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
