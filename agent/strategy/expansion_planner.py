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
# Dynamic land ROI estimation
# ---------------------------------------------------------------------------

TILES_PER_QUADRANT = 25  # 5x5 grid per quadrant

def _estimate_crop_revenue_per_tile(crop, plant_day, current_day,
                                     forecast, n_own_tiles=0, n_opp_tiles=0):
    """Estimate expected revenue per tile for a crop planted on plant_day.

    Uses the crop's harvest schedule and expected market prices,
    accounting for own-supply glut and opponent supply.
    """
    cd = CROPS[crop]
    econ = CROP_ECONOMICS[crop]
    cycle_len = CROP_CYCLE_LEN[crop]

    # Compute harvest days
    if cd["ongoing"]:
        harvest_days = []
        d = plant_day + cd["first_yield_day"]
        while d <= 29:
            harvest_days.append(d)
            d += cd["interval"]
        if not harvest_days:
            return 0.0, 0
        units_per_harvest = cd["max_yield"]
    else:
        harvest_day = plant_day + cd["max_yield_day"]
        if harvest_day > 29:
            return 0.0, 0
        harvest_days = [harvest_day]
        units_per_harvest = cd["max_yield"]

    # Only count harvests that haven't happened yet
    future_harvests = [h for h in harvest_days if h >= current_day]
    if not future_harvests:
        return 0.0, 0

    total_revenue = 0.0
    total_units = 0
    for h in future_harvests:
        # Own-supply glut: each tile's production adds to market inventory
        # Approximate: own tiles reduce price by ~2% per tile
        own_discount = max(0.7, 1.0 - 0.02 * n_own_tiles)
        opp_discount = max(0.8, 1.0 - 0.01 * n_opp_tiles)
        price = forecast.expected_price(crop, h) * own_discount * opp_discount
        revenue = units_per_harvest * price
        total_revenue += revenue
        total_units += units_per_harvest

    # Deduct seed cost (one-time per cycle)
    seed_cost = cd["seed"]
    # Deduct fertilizer cost if applicable
    fert_cost = econ["apps"] * 25.0  # ~$25 per fert app

    net_revenue = total_revenue - seed_cost - fert_cost
    return net_revenue, total_units


def _candidate_crop_mix_for_quadrant(next_quadrant, current_day, forecast,
                                      n_tiles, n_own_tiles, n_opp_tiles):
    """Generate candidate crop mixes for a quadrant and score each.

    Returns list of (mix_dict, expected_revenue_per_tile, total_revenue).
    """
    # Determine which crops are eligible
    eligible = []
    for crop in CROPS:
        if not _crop_allowed_quick(crop, current_day):
            continue
        cap = CROP_TILE_CAPS.get(crop, 99)
        eligible.append((crop, cap))

    if not eligible:
        return []

    # Generate candidate mixes
    candidates = []

    # Strategy 1: All-in on highest-scoring crop
    best_crop = None
    best_revenue = -1e9
    for crop, cap in eligible:
        n = min(n_tiles, cap)
        rev, _ = _estimate_crop_revenue_per_tile(
            crop, current_day, current_day, forecast,
            n_own_tiles, n_opp_tiles)
        if rev > best_revenue:
            best_revenue = rev
            best_crop = crop
    if best_crop:
        n = min(n_tiles, CROP_TILE_CAPS.get(best_crop, 99))
        candidates.append({best_crop: n})

    # Strategy 2: Diversified mix (top 2-3 crops by revenue)
    scored = []
    for crop, cap in eligible:
        rev, _ = _estimate_crop_revenue_per_tile(
            crop, current_day, current_day, forecast,
            n_own_tiles, n_opp_tiles)
        scored.append((crop, rev, cap))
    scored.sort(key=lambda x: -x[1])

    # Top crop gets half, rest split remaining
    if len(scored) >= 2:
        mix = {}
        remaining = n_tiles
        for i, (crop, rev, cap) in enumerate(scored[:3]):
            if i == 0:
                n = min(remaining, cap, n_tiles // 2)
            else:
                n = min(remaining, cap, remaining // max(1, 3 - i))
            if n > 0:
                mix[crop] = n
                remaining -= n
        if mix:
            candidates.append(mix)

    # Strategy 3: Strawberry-heavy (for SW before deadline)
    if next_quadrant == 3 and current_day <= STRAWBERRY_PLANT_DEADLINE:
        straw_cap = CROP_TILE_CAPS.get("STRAWBERRY", 10)
        rev, _ = _estimate_crop_revenue_per_tile(
            "STRAWBERRY", current_day, current_day, forecast,
            n_own_tiles, n_opp_tiles)
        if rev > 0:
            straw_n = min(n_tiles, straw_cap, 12)
            remaining = n_tiles - straw_n
            mix = {"STRAWBERRY": straw_n}
            # Fill rest with tomato if eligible
            if remaining > 0:
                for crop, cap in eligible:
                    if crop != "STRAWBERRY":
                        n = min(remaining, cap, remaining)
                        if n > 0:
                            mix[crop] = n
                            remaining -= n
                            break
            candidates.append(mix)

    # Strategy 4: Tomato-heavy (ongoing crop, good late-season value)
    if "TOMATO" in [c for c, _ in eligible]:
        tomato_cap = CROP_TILE_CAPS.get("TOMATO", 14)
        rev, _ = _estimate_crop_revenue_per_tile(
            "TOMATO", current_day, current_day, forecast,
            n_own_tiles, n_opp_tiles)
        if rev > 0:
            tomato_n = min(n_tiles, tomato_cap, 10)
            remaining = n_tiles - tomato_n
            mix = {"TOMATO": tomato_n}
            # Fill rest with best remaining crop
            for crop, cap in eligible:
                if crop != "TOMATO":
                    n = min(remaining, cap, remaining)
                    if n > 0:
                        mix[crop] = n
                        remaining -= n
                        break
            candidates.append(mix)

    # Score each candidate
    scored_candidates = []
    for mix in candidates:
        total_rev = 0
        for crop, n in mix.items():
            rev, _ = _estimate_crop_revenue_per_tile(
                crop, current_day, current_day, forecast,
                n_own_tiles, n_opp_tiles)
            total_rev += rev * n
        avg_rev = total_rev / max(1, sum(mix.values()))
        scored_candidates.append((mix, avg_rev, total_rev))

    scored_candidates.sort(key=lambda x: -x[1])
    return scored_candidates


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
    if crop == "MELON":
        return day <= 17  # MELON_PLANT_DEADLINE
    return True


def compute_land_roi(next_quadrant, current_day, money, farm, forecast,
                     n_own_tiles=0, n_opp_tiles=0):
    """Estimate marginal expected value of buying the next quadrant today.

    Returns (roi: float, info: dict).
    roi = expected_incremental_profit / land_cost
    roi > 1.0 means the land pays for itself.
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

    # Generate candidate crop mixes and pick the best
    candidates = _candidate_crop_mix_for_quadrant(
        next_quadrant, current_day, forecast,
        TILES_PER_QUADRANT, n_own_tiles, n_opp_tiles)

    if not candidates:
        return 0.0, {"reason": "no_eligible_crops"}

    best_mix, best_avg_rev, best_total_rev = candidates[0]

    # Expected profit = total revenue - land cost - seed costs
    seed_costs = sum(CROPS[c]["seed"] * n for c, n in best_mix.items())
    expected_profit = best_total_rev - land_price - seed_costs

    # Account for capital opportunity cost: money spent on land can't earn interest
    # Approximate: 5% opportunity cost for remaining season
    opp_cost_factor = 1.0 - 0.05 * (days_left / 30.0)
    expected_profit *= opp_cost_factor

    roi = expected_profit / max(1, land_price)

    return roi, {
        "land_price": land_price,
        "best_mix": best_mix,
        "best_total_rev": round(best_total_rev, 0),
        "seed_costs": seed_costs,
        "expected_profit": round(expected_profit, 0),
        "days_left": days_left,
        "roi": round(roi, 2),
    }


def opportunity_window_factor(next_quadrant, current_day):
    """Time-window factor that declines as key crop deadlines approach.

    Returns 1.0 when plenty of time, declining to 0.0 after deadline.
    This MODIFIES the ROI but does NOT replace urgency.
    """
    if next_quadrant == 3:
        deadline = STRAWBERRY_PLANT_DEADLINE
    elif next_quadrant == 2:
        deadline = MELON_PLANT_DEADLINE
    else:
        return 1.0

    days_to_deadline = deadline - current_day
    if days_to_deadline <= 0:
        return 0.0  # deadline passed — value is zero
    elif days_to_deadline <= 2:
        return 0.3  # very low — almost no time to profit
    elif days_to_deadline <= 4:
        return 0.6  # low — limited production window
    elif days_to_deadline <= 7:
        return 0.8  # moderate
    else:
        return 1.0  # full value — plenty of time


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

    # v5.11: Combine ROI with opportunity window
    adjusted_roi = roi * ow_factor

    # v5.11: STRICT GATE — adjusted_roi must be positive to buy
    if adjusted_roi <= 0:
        return False, f"adjusted_roi_{adjusted_roi:.2f}_non_positive", {
            "land_price": land_price,
            "mandatory": mandatory,
            "seed_cost": seed_cost,
            "reserve": reserve,
            "total_required": total_required,
            "roi": roi,
            "ow_factor": ow_factor,
            "adjusted_roi": adjusted_roi,
        }

    if money >= total_required:
        return True, "treasury_sufficient_roi_positive", {
            "land_price": land_price,
            "mandatory": mandatory,
            "seed_cost": seed_cost,
            "reserve": reserve,
            "total_required": total_required,
            "roi": roi,
            "ow_factor": ow_factor,
            "adjusted_roi": adjusted_roi,
        }
    else:
        shortfall = total_required - money
        return False, f"short_{shortfall:.0f}", {
            "land_price": land_price,
            "mandatory": mandatory,
            "seed_cost": seed_cost,
            "reserve": reserve,
            "total_required": total_required,
            "shortfall": shortfall,
            "roi": roi,
            "ow_factor": ow_factor,
            "adjusted_roi": adjusted_roi,
        }


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
