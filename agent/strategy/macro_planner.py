"""W2: Macro strategic planner — turns validated price forecasts + asset
economics + live farm/money state into the daily MacroPlan consumed by
execution.task_scheduler.

Inputs (per call):
  ctx        parsed observation (farm, private, town)
  forecast   PriceForecast (W1) — E[P|day], tails, floor probabilities
  boosts     optional {product: count} from strategy.shop_adapter

Outputs (MacroPlan):
  fields consumed by task_scheduler today:
    watering_enabled, water_budget_exceeded, feeding_enabled,
    plant_queue [(pos, crop)], build_queue [pos], build_op (single op/day),
    place_queue [{op,target,args}]
  plus purchase intents consumed by the future order_builder/main wiring:
    intents = {hire, buy_land, buy_seed{crop:n}, buy_animal{animal:k},
               buy_wheat:n}

Economics constants here MIRROR simulations/profitability_calculator values
(SEASON_YIELD_PER_TILE / SEASON_COST_PER_TILE / OPTIMAL_FERT_DAYS /
ANIMAL outputs). Mirror risk is tracked by impact-analysis; keep both sides
in sync or derive them from one baked artifact later.

Wheat capacity projection:
  The planner projects total wheat production from existing wheat tiles,
  computes a sustainable animal count, and dynamically caps animal
  expansion. When wheat production can't sustain the current herd,
  deficit-triggered wheat purchases are queued to prevent starvation.

Known simplifications (documented, deliberate):
  - fertilizer applied on the recommended schedule only (melons/tomato/
    strawberry), mirroring the distributional-ROI winning variants
  - one structure type queued per day (task_scheduler exposes a single
    build_op); coops take priority over pastures
  - animal revenue model: care-enabled output rates (latest engine rules)
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple, Set, Union

from config import (
    ANIMAL_CARE_CUTOFF_DAY,
    ANIMAL_EXPANSION_HORIZON_DAYS,
    ANIMAL_FEED_CUTOFF_DAY,
    ANIMAL_LIST,
    ANIMALS,
    CROP_DIVERSIFICATION_FACTOR,
    CROP_TILE_CAPS,
    CROPS,
    ENDGAME_START_DAY,
    FEED_OPERATIONAL_HORIZON_DAYS,
    FEED_WHEAT_BUFFER_DAYS,
    HIRE_BUDGET_MAX_HANDS,
    LAND_BUY_LAST_DAY,
    LAND_ORDER,
    LAND_PRICES,
    LAND_ROI_THRESHOLD,
    MARKET_I0,
    MAX_ANIMAL_BUYS_PER_DAY,
    MELON_PLANT_LAST_DAY_FERT,
    PHASE1_GEESE_DAY0_2,
    PHASE1_WHEAT_TILES,
    SEASON_DAYS,
    STARTING_MONEY,
    TARGET_COWS,
    TARGET_GEESE,
    TARGET_SHEEP,
    TURNS_PER_DAY,
    STRAWBERRY_PLANT_DEADLINE,
    PRE_BUY_LEAD_DAYS,
    SW_SEED_TARGETS,
    NE_SEED_TARGETS,
    PORT_SW,
    SW_PASTURE_TILES,
    EARLY_PASTURE_TILES,
    SHED_ACCESS_TILES,
    SW_SOIL_TILES,
    SW_ESCROW_AMOUNT,
    get_target_hands,
    QUADRANT_UNLOCK_DAYS,
    QUADRANT_MONEY_THRESHOLDS,
    QUADRANT_HARD_BLOCK,
    get_strawberry_cap,
    get_sw_seed_targets,
    C4_LIVESTOCK_CUTOFF_DAY,
    get_point2_feed_mode,
)
try:
    from strategy.feed_feasibility import (
        build_feed_resource_ledger,
        evaluate_existing_herd_feasibility,
        evaluate_incremental_candidate,
        commit_candidate_reservation,
    )
except ImportError:
    try:
        from feed_feasibility import (
            build_feed_resource_ledger,
            evaluate_existing_herd_feasibility,
            evaluate_incremental_candidate,
            commit_candidate_reservation,
        )
    except ImportError:
        build_feed_resource_ledger = None
        evaluate_existing_herd_feasibility = None
        evaluate_incremental_candidate = None
        commit_candidate_reservation = None
try:
    from strategy.animal_planner import get_animal_targets, HERD_CAP
    from strategy.pasture_planner import (
        evaluate_pasture_candidates,
        estimate_crop_opportunity_value,
        BUILD_ACTION_OPPORTUNITY_COST,
    )
except ImportError:
    from animal_planner import get_animal_targets, HERD_CAP
    from pasture_planner import (
        evaluate_pasture_candidates,
        estimate_crop_opportunity_value,
        BUILD_ACTION_OPPORTUNITY_COST,
    )
from strategy.expansion_planner import (
    compute_land_urgency,
    compute_land_roi,
    opportunity_window_factor,
    should_buy_land,
    compute_pre_buy_seeds,
    expansion_crop_priorities,
    expansion_seed_targets,
    TILES_PER_QUADRANT,
)
from market.price_math import inventory_at_price, market_price
from market.order_builder import hire_total_cost

try:
    from execution.task_scheduler import get_sw_tile_breakdown
except ImportError:
    from task_scheduler import get_sw_tile_breakdown

try:
    from strategy.marginal_livestock_valuator import (
        estimate_realized_marginal_animal_value,
        select_guarded_livestock_candidate,
    )
except ImportError:
    try:
        from marginal_livestock_valuator import (
            estimate_realized_marginal_animal_value,
            select_guarded_livestock_candidate,
        )
    except ImportError:
        estimate_realized_marginal_animal_value = None
        select_guarded_livestock_candidate = None

# ---------------------------------------------------------------------------
# Asset economics — imported from authoritative baked_economics artifact.
# ---------------------------------------------------------------------------
try:
    from strategy.baked_economics import (
        ANIMAL_ECONOMICS,
        BOOST_CAP,
        CROP_CYCLE_LEN,
        CROP_ECONOMICS,
        MONEY_RESERVE,
        SHOP_BOOST_WEIGHT,
    )
except ImportError:
    from baked_economics import (
        ANIMAL_ECONOMICS,
        BOOST_CAP,
        CROP_CYCLE_LEN,
        CROP_ECONOMICS,
        MONEY_RESERVE,
        SHOP_BOOST_WEIGHT,
    )


_LIVESTOCK_DECISION_LOGS: List[Dict[str, Any]] = []


def get_livestock_decision_logs() -> List[Dict[str, Any]]:
    """Return all recorded livestock purchase decision telemetry."""
    return list(_LIVESTOCK_DECISION_LOGS)


def clear_livestock_decision_logs() -> None:
    """Clear recorded livestock purchase decision telemetry."""
    global _LIVESTOCK_DECISION_LOGS
    _LIVESTOCK_DECISION_LOGS = []


def _log_livestock_decision(day: int, hour: int, town_shops: list, current_herd: dict, cands_eval: dict, selected: Optional[str], reason: str, guard_diag: Optional[dict] = None) -> None:
    record = {
        "day": int(day),
        "hour": int(hour),
        "town_shops": list(town_shops),
        "current_herd": dict(current_herd),
        "selected_species": selected,
        "decision_reason": reason,
        "guard_diag": guard_diag,
        "candidates": {},
    }
    for sp, data in cands_eval.items():
        ev = data.get("eval", {})
        record["candidates"][sp] = {
            "net_realized_value": ev.get("net_realized_value", 0.0),
            "marginal_product_revenue": ev.get("marginal_product_revenue", 0.0),
            "gross_fertilizer_revenue": ev.get("gross_fertilizer_revenue", 0.0),
            "feed_cost": ev.get("feed_cost", 0.0),
            "purchase_cost": data.get("cost", 0.0),
            "housing_cost": data.get("housing_cost", 0.0),
            "feed_reserve": data.get("feed_reserve", 0.0),
            "labor_housing_deductions": data.get("housing_cost", 0.0),
        }
    _LIVESTOCK_DECISION_LOGS.append(record)


@dataclass
class MacroPlan:
    day: int
    phase: str = ""
    watering_enabled: bool = True
    water_budget_exceeded: bool = False
    feeding_enabled: bool = True
    plant_queue: list = field(default_factory=list)      # [(pos, crop)]
    build_queue: list = field(default_factory=list)      # [pos]
    build_op: str = "BUILD_PASTURE"
    place_queue: list = field(default_factory=list)      # [{op,target,args}]
    intents: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)      # v5.10: expansion observability
    buy_animal_sequence: list = field(default_factory=list)  # Phase C1: ordered provisional sequence


def _crop_allowed_today(crop, day):
    """True if planted today it still completes its final harvest by day 29."""
    if day > 25 and not (crop == "CARROT" and day <= 27):
        return False  # STOP seed purchases after day 25, except Day 25-27 Carrot Blitz
    cd = CROPS[crop]
    if cd["ongoing"]:
        # latest scheduled production: first + (count-1) * interval
        last_harvest = cd["first_yield_day"] + (cd["max_yield"] - 1) * cd["interval"]
    elif crop == "CARROT" and day == 27:
        last_harvest = cd["first_yield_day"]  # yields on Day 29 (EV = +102.5/tile)
    else:
        last_harvest = cd["max_yield_day"]
    if day + last_harvest > 29:
        return False
    if crop == "MELON":
        return day <= MELON_PLANT_LAST_DAY_FERT   # fert variant assumed
    return True


def _harvest_days(crop, day):
    cyc = CROP_CYCLE_LEN[crop]
    hday = cyc - 1
    days = []
    start = day
    while start + hday <= 29:
        days.append(start + hday)
        start += cyc
    return days


def _cycle_yield(crop):
    econ = CROP_ECONOMICS[crop]
    cyc = CROP_CYCLE_LEN[crop]
    cycles = len(_harvest_days(crop, 0)) or 1
    # yield30 in economics already reflects the chosen (fert) variant cycles
    return econ["yield30"] / max(cycles, 1)


# ---------------------------------------------------------------------------
# Own-supply glut pricing helpers
# ---------------------------------------------------------------------------

def _cum_town_drain(forecast, crop, harvest_day):
    """Invert the town-only forecast price to implied inventory, return drain.

    The exhaustive reference E[P|day] encodes the full town drain path.
    Inverting it gives the inventory that would produce that price, and
    I0 minus that inventory is the cumulative town drain by that day.

    NOTE ON JENSEN'S INEQUALITY:
    Inverting E[P|day] to estimate implied inventory
    (I_implied = f^-1(E[P])) ignores Jensen's inequality
    (E[price(inv)] != price(E[inv])) for non-linear price curves
    (sqrt, log, sq, hinge). This produces a deterministic point-estimate
    approximation of the true distributional town drain. Because the error
    is monotonic across price regimes, it preserves exact relative crop ROI
    ranking while maintaining O(1) runtime efficiency during real-time
    planning turns.
    """
    price = forecast.expected_price(crop, harvest_day)
    inv_implied = inventory_at_price(crop, price)
    return max(0.0, MARKET_I0 - inv_implied)


def _project_avg_herd(n_animals, day, season_end=29):
    """Project time-weighted average herd size from now through season end.

    The herd ramps from n_animals toward TARGET_GEESE+TARGET_COWS+TARGET_SHEEP
    at MAX_ANIMAL_BUYS_PER_DAY, bounded by the expansion horizon.
    """
    target_total = TARGET_GEESE + TARGET_COWS + TARGET_SHEEP
    remaining = max(0, season_end - day)
    ramp_limit = min(target_total,
                     n_animals + min(remaining, ANIMAL_EXPANSION_HORIZON_DAYS)
                     * MAX_ANIMAL_BUYS_PER_DAY)
    return (n_animals + ramp_limit) / 2.0


def _cum_own_production(crop, own_tiles, harvest_index, feed_wheat_per_day=0,
                        harvest_day=0, plant_day=0, n_animals=0):
    """Cumulative own production sold by the harvest_index-th harvest.

    For one-time crops: all units arrive at harvest_day.
    For ongoing crops: units arrive at each harvest day.
    Wheat feed offset deducts projected herd consumption (ramp-adjusted).
    """
    cy = _cycle_yield(crop)
    cum_raw = own_tiles * cy * harvest_index
    if crop == "WHEAT" and feed_wheat_per_day > 0:
        # P1: project average herd across remaining days instead of static snapshot
        avg_herd = _project_avg_herd(n_animals, plant_day)
        days_elapsed = max(0, harvest_day - plant_day)
        cum_raw = max(0.0, cum_raw - avg_herd * days_elapsed)
    return cum_raw


def get_committed_crop_counts(farm, planned=None):
    """Farm-wide count of crops committed across the farm.

    Evaluates live tiles (is_plant is True, crop in CROPS, consecutive_unwatered < 2)
    plus crops already planned for planting during this turn.
    Dead crops, harvested tiles, or replaced tiles are not counted.
    """
    counts = {crop: 0 for crop in CROPS}
    if farm is not None and hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if (getattr(t, "is_plant", False) and
                getattr(t, "crop", None) in counts and
                getattr(t, "consecutive_unwatered", 0) < 2):
                counts[t.crop] += 1
    if planned:
        for crop, cnt in planned.items():
            if crop in counts:
                counts[crop] += cnt
    return counts


def _crop_score(crop, day, forecast, boosts, own_tiles=0,
                feed_wheat_per_day=0, n_animals=0, opp_advice=None):
    """Expected net coins for ONE tile planted today with this crop.

    Uses post-own-supply pricing: effective_inventory = I0 - town_drain + own.
    This penalizes crops where the agent's own production gluts the market
    (e.g. melon, strawberry) while allowing deep-curve crops (wheat, carrot)
    to remain competitive.

    P3: own_tiles is scaled by CROP_DIVERSIFICATION_FACTOR to avoid phantom
    mono-crop over-penalization when the actual portfolio is diversified.

    Phase 6: opp_advice adds opponent supply glut to effective inventory and
    applies a counter-pick monopoly boost for uncompeted crops.
    """
    e = CROP_ECONOMICS[crop]
    hdays = _harvest_days(crop, day)
    if not hdays:
        return -1e9, {}
    cy = _cycle_yield(crop)
    plant_day = day
    # P3: diversification discount — assume realistic max share, not 100%
    div_factor = CROP_DIVERSIFICATION_FACTOR.get(crop, 0.60)
    effective_tiles = own_tiles * div_factor if own_tiles > 0 else 0
    details = {"eff_prices": {}, "cum_own": {}}
    score = 0.0
    # Phase 6: opponent supply adjustment — extra units opponent will flood
    opp_supply = 0.0
    if opp_advice is not None:
        opp_supply = opp_advice.supply_adjustment.get(crop, 0.0)
    # Phase 6: counter-pick monopoly boost — opponent ignoring this crop
    counter_pick_boost = 1.0
    if opp_advice is not None and crop in opp_advice.counter_pick:
        counter_pick_boost = 1.15  # +15% revenue for uncompeted niche
    for idx, h in enumerate(hdays, 1):
        cum_town = _cum_town_drain(forecast, crop, h)
        cum_own = _cum_own_production(crop, effective_tiles, idx,
                                      feed_wheat_per_day, h, plant_day,
                                      n_animals)
        inv_eff = MARKET_I0 - cum_town + cum_own + opp_supply
        p = market_price(crop, inv_eff)
        f = min(1.0 + SHOP_BOOST_WEIGHT * boosts.get(crop, 0), BOOST_CAP)
        details["eff_prices"][h] = round(p * f * counter_pick_boost, 2)
        details["cum_own"][h] = int(cum_own)
        score += cy * p * f * counter_pick_boost
    cd = CROPS[crop]
    econ = CROP_ECONOMICS[crop]
    fert_apps = econ.get("apps", 0)
    fert_cost_per_app = 25.0
    cycles = len(hdays) if not cd["ongoing"] else (1 if len(hdays) > 0 else 0)
    real_cost = cycles * (cd["seed"] + fert_apps * fert_cost_per_app)
    net = score - real_cost
    per_day = net / max(1, 30 - day)
    return per_day, details


# ---------------------------------------------------------------------------
# Wheat capacity projection — dynamic animal-cap / buy-wheat controller
# ---------------------------------------------------------------------------

def project_wheat_harvests(plant_day, current_day, season_end=29):
    """Wheat units a tile planted on plant_day will yield through season_end.

    Wheat is one-time: first_yield_day=2, max_yield_day=4, max_yield=6.
    Produces max_yield units once at plant_day + max_yield_day.
    """
    if plant_day is None:
        # Unknown crop age is not secured future supply.
        return 0
    cd = CROPS["WHEAT"]
    harvest_day = plant_day + cd["max_yield_day"]
    if harvest_day > season_end:
        return 0
    return cd["max_yield"]


def compute_wheat_capacity(wheat_tiles, current_day, season_end=29):
    """Total wheat units producible from existing tiles through season end."""
    return sum(project_wheat_harvests(td, current_day, season_end)
               for td in wheat_tiles if td is not None)


def compute_sustainable_animals(wheat_capacity, days_left, wheat_per_animal=1):
    """Max animals whose season-long feed demand can be met from capacity.

    animals × days_left × wheat_per_animal ≤ wheat_capacity
    """
    if days_left <= 0 or wheat_per_animal <= 0:
        return 0
    return wheat_capacity // (days_left * wheat_per_animal)


def compute_authoritative_feed_capacity(farm, private, day, season_end=28, current_animals_count=0):
    """Authoritative projected wheat supply and sustainable herd calculation.

    Components of feed supply:
      1. Wheat on hand: shed inventory + worker inventories.
      2. Expected wheat from existing planted wheat maturing on or before season_end (Day 28).
      3. Expected wheat from already-planned wheat planting where reasonably predictable.
      4. Affordable emergency/market wheat purchases if intentional.
    """
    days_left = SEASON_DAYS - day
    feeding_days_left = max(1, season_end - day + 1) if day <= season_end else 0

    # 1. Wheat on hand
    shed_wheat = int(private.shed.get("WHEAT", 0)) if hasattr(private, "shed") else 0
    worker_wheat = 0
    if hasattr(private, "inventories"):
        worker_wheat = sum(int(inv.get("WHEAT", 0)) for inv in private.inventories)
    wheat_on_hand = shed_wheat + worker_wheat

    # 2. Existing planted wheat yield
    wheat_tiles = [t for t in farm.iter_tiles() if getattr(t, "is_plant", False) and getattr(t, "crop", None) == "WHEAT"]
    planted_yield = 0
    for t in wheat_tiles:
        planted_day = getattr(t, "planted_day", None)
        # A live crop with an unknown planting timestamp must not manufacture
        # future feed credit. TileView exposes crop timing via planted_day.
        if planted_day is None:
            continue
        harvest_day = planted_day + CROPS["WHEAT"]["max_yield_day"]
        if harvest_day <= season_end:
            fert_day = getattr(t, "fertilized_until_day", None)
            is_fert = fert_day is not None and fert_day >= planted_day
            planted_yield += (6 if is_fert else 4)

    # 3. Predictable planned wheat yield
    planned_yield = 0
    if day <= 4:
        nw_empty = sum(1 for t in farm.iter_tiles() if getattr(t, "kind", None) == "EMPTY" and farm.quadrant_of(t.pos) == "NW")
        needed_nw = max(0, PHASE1_WHEAT_TILES - len(wheat_tiles))
        can_plant = min(nw_empty, needed_nw)
        if day + 4 <= season_end:
            planned_yield += can_plant * 4
    elif "SW" in farm.unlocked and day <= 24:
        sw_soil_empty = sum(1 for t in farm.iter_tiles() if getattr(t, "kind", None) == "EMPTY" and t.pos in SW_SOIL_TILES)
        if sw_soil_empty > 0 and day + 4 <= season_end:
            try:
                from strategy.land_serviceability_model import evaluate_sw_serviceability
                _, best_k, _ = evaluate_sw_serviceability(day, farm, getattr(farm, "money", 0), None, target_quadrant=3)
            except Exception:
                best_k = sw_soil_empty
            sw_alloc = sw_plant_decision(day, sw_soil_empty, wheat_on_hand + planted_yield, current_animals_count, max_tiles=best_k)
            planned_yield += sw_alloc.get("WHEAT", 0) * 4

    # 4. Affordable emergency market wheat purchases
    wheat_spot = 25
    money = getattr(farm, "money", 0)
    discretionary_cash = max(0.0, money - 300 - 150)
    affordable_wheat = min(100, int(discretionary_cash // wheat_spot))

    projected_feed_supply = wheat_on_hand + planted_yield + planned_yield + affordable_wheat

    if feeding_days_left <= 0:
        sustainable_herd_size = HERD_CAP
    else:
        sustainable_herd_size = int(projected_feed_supply // feeding_days_left)

    return {
        "projected_wheat_supply": projected_feed_supply,
        "feeding_days_left": feeding_days_left,
        "sustainable_herd_size": sustainable_herd_size,
        "wheat_on_hand": wheat_on_hand,
        "planted_yield": planted_yield,
        "planned_yield": planned_yield,
        "affordable_wheat": affordable_wheat,
    }


def compute_unavoidable_feed_shortfall(farm, private, day, n_animals, feed_buffer, wheat_unit_price=None, ctx=None):
    """Compute unavoidable survival feed shortfall for existing animals.

    Reuses authoritative feed projections and enforces strict temporal validity:
    - Immediately usable wheat: shed inventory + worker-held inventory.
    - Future wheat harvests from in-ground tiles: can only cover feeding on/after
      their arrival day. Future harvests cannot cover near-term hunger.
    Returns (wheat_on_hand, projected_wheat_req, shortfall_units, shortfall_cost).
    """
    if wheat_unit_price is None:
        try:
            from market.price_math import estimate_wheat_buy_price
            wheat_unit_price = estimate_wheat_buy_price(ctx) if ctx is not None else 25.0
        except Exception:
            wheat_unit_price = 25.0

    if n_animals <= 0:
        return 0, 0, 0, 0.0

    shed_wheat = int(private.shed.get("WHEAT", 0)) if hasattr(private, "shed") and isinstance(private.shed, dict) else 0
    worker_wheat = 0
    if hasattr(private, "inventories") and isinstance(private.inventories, list):
        for inv in private.inventories:
            if isinstance(inv, dict):
                worker_wheat += int(inv.get("WHEAT", 0))
    wheat_on_hand = shed_wheat + worker_wheat

    days_left = max(0, SEASON_DAYS - day)
    buffer_days = max(1, min(int(feed_buffer), days_left)) if days_left > 0 else 0
    if buffer_days == 0:
        return wheat_on_hand, 0, 0, 0.0

    # Collect existing in-ground wheat tile harvest schedules
    wheat_harvests = []
    if hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if t is None or t == "LOCKED":
                continue
            is_plant = getattr(t, "is_plant", False) if not isinstance(t, dict) else (t.get("is_plant", False) or t.get("kind") == "PLANT")
            crop = getattr(t, "crop", None) if not isinstance(t, dict) else t.get("crop")
            if is_plant and crop == "WHEAT":
                planted_day = getattr(t, "planted_day", None) if not isinstance(t, dict) else t.get("planted_day")
                # Missing crop age is unknown supply, not a crop planted today.
                if planted_day is None:
                    continue
                h_day = planted_day + CROPS["WHEAT"]["max_yield_day"]
                fert_day = getattr(t, "fertilized_until_day", None) if not isinstance(t, dict) else t.get("fertilized_until_day")
                is_fert = fert_day is not None and fert_day >= planted_day
                yield_units = 6 if is_fert else 4
                wheat_harvests.append((h_day, yield_units))

    max_deficit = 0
    for k in range(buffer_days):
        target_day = day + k
        cumulative_needed = n_animals * (k + 1)
        maturing_by_target = sum(y for h_day, y in wheat_harvests if h_day <= target_day)
        cumulative_supply = wheat_on_hand + maturing_by_target
        deficit = max(0, cumulative_needed - cumulative_supply)
        if deficit > max_deficit:
            max_deficit = deficit

    projected_req = n_animals * buffer_days
    shortfall_cost = float(max_deficit * wheat_unit_price)
    return wheat_on_hand, projected_req, max_deficit, shortfall_cost


def detect_wheat_deficit(wheat_capacity, wheat_have, days_left,
                         n_animals, buffer_days):
    """Projected wheat shortfall before starvation.

    Returns (deficit, trigger). deficit > 0 means wheat runs out before
    season ends; trigger is True only when the buffer is critically low
    AND production can't refill it before animals starve.
    """
    total_demand = n_animals * days_left + n_animals * buffer_days
    total_supply = wheat_have + wheat_capacity
    deficit = max(0, total_demand - total_supply)
    daily_consumption = n_animals
    buffer_risk = wheat_have < daily_consumption * buffer_days
    # trigger only if buffer is low AND season-long supply can't cover demand
    trigger = buffer_risk and deficit > 0
    return deficit, trigger


def sw_plant_decision(day: int, free_tiles: int, wheat_stock: int, herd_size: int, max_tiles: Optional[int] = None) -> dict:
    """Computes exact wheat and carrot seed allocation for free SW soil tiles.

    Mathematical specification:
    - Day >= 28: Fallow / harvest-only (0 seeds).
    - If max_tiles is specified, caps free_tiles to max_tiles.
    - Day <= 25 and wheat_stock < feed_need: Allocate needed wheat seeds (ceil div).
    - Remainder of free tiles go to CARROT.
    - Day 27 EV gate: 0.5 * 3.5 * 70 - 20 = +102.5 > 0, so carrots are planted.
    """
    if day >= 28:
        return {"WHEAT": 0, "CARROT": 0}
    if max_tiles is not None:
        free_tiles = min(free_tiles, max_tiles)
    feed_need = herd_size * (29 - day + 1)
    n_wheat = 0
    if day <= 25 and wheat_stock < feed_need:
        deficit = feed_need - wheat_stock
        n_wheat = min(free_tiles, (deficit + 4) // 5)  # ceil div
    n_carrot = max(0, free_tiles - n_wheat)
    if day == 27 and (0.5 * 3.5 * 70 - 20) <= 0:
        n_carrot = 0
    return {"WHEAT": n_wheat, "CARROT": n_carrot}


def evaluate_dynamic_sw_crop_choice(
    day: int,
    wheat_have: int,
    n_animals: int,
    forecast: Any,
    boosts: Any,
    committed_counts: Dict[str, int],
    opp_advice: Any = None,
    return_ev: bool = False,
) -> Union[str, Tuple[str, float]]:
    """Select the best crop for a single SW tile using authoritative _crop_score().

    Dual valuation of wheat:
      - feed wheat: min(SW wheat yield, unavoidable feed shortfall) * replacement_price ($30)
      - sale wheat: excess reverts strictly to normal market sale economics
    Spatial SW penalty:
      - exceptional travel & labor overhead (~2.0 effective actions per tile-day)
    """
    days_left = max(1, 29 - day + 1)
    feed_need = n_animals * days_left
    unavoidable_shortfall = max(0, feed_need - wheat_have)

    best_crop = "WHEAT"
    best_ev = -1e9

    candidate_crops = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]

    for crop in candidate_crops:
        if not _crop_allowed_today(crop, day):
            continue

        per_day, details = _crop_score(
            crop=crop,
            day=day,
            forecast=forecast,
            boosts=boosts or {},
            own_tiles=committed_counts.get(crop, 0),
            feed_wheat_per_day=n_animals,
            n_animals=n_animals,
            opp_advice=opp_advice,
        )
        if per_day <= -1e8:
            continue

        total_net = per_day * max(1, 30 - day)

        if crop == "WHEAT":
            wheat_yield = 4
            feed_units = min(wheat_yield, unavoidable_shortfall)
            sale_units = max(0, wheat_yield - feed_units)
            # Avoided market purchase cost ($30)
            feed_val = feed_units * 30.0
            eff_p = list(details.get("eff_prices", {}).values())
            sale_price = eff_p[0] if eff_p else 25.0
            sale_val = sale_units * sale_price
            seed_cost = CROPS["WHEAT"]["seed"]
            total_net = feed_val + sale_val - seed_cost

        # Calibrated SW spatial penalty:
        # 1.3 ops/tile/day + exceptional travel ~0.7 actions = 2.0 actions/tile/day
        # Opportunity cost per action ≈ $1.0
        sw_labor_penalty = 2.0 * 1.0 * max(1, 30 - day)
        net_ev = total_net - sw_labor_penalty

        if net_ev > best_ev:
            best_ev = net_ev
            best_crop = crop

    if return_ev:
        return best_crop, (best_ev if best_ev > -1e8 else 0.0)
    return best_crop


class MacroPlanner:
    """Produces the daily MacroPlan. Stateless w.r.t. previous calls."""

    def __init__(self, forecast, money_reserve=MONEY_RESERVE):
        self.fc = forecast
        self.reserve = money_reserve

    # ------------------------------------------------------------------
    def build(self, ctx, boosts=None, opp_advice=None):
        boosts = boosts or {}
        day = ctx["day"]
        hour = ctx.get("hour", 0)
        farm = ctx["farm"]
        private = ctx["private"]
        plan = MacroPlan(day=day)

        try:
            from config import get_point2_feed_mode
            point2_mode = get_point2_feed_mode()
        except Exception:
            point2_mode = "shadow"

        town_obj = ctx.get("town")
        town_shops = []
        if town_obj:
            town_shops = list(getattr(town_obj, "unlocked_shops", None) or (town_obj.get("unlocked_shops", []) if isinstance(town_obj, dict) else []))

        market_obj = ctx.get("market")
        market_inv = {}
        if market_obj:
            market_inv = dict(getattr(market_obj, "inventory", None) or (market_obj.get("inventory", {}) if isinstance(market_obj, dict) else {}))

        opp_farm = ctx.get("opponent_farm")
        opp_livestock_supply = None
        opp_stress_supply = None
        guard_threshold = 0.15
        try:
            from config import LIVESTOCK_VALUATION_MODE, get_livestock_guard_threshold
            guard_threshold = get_livestock_guard_threshold()
            if opp_farm is not None:
                if LIVESTOCK_VALUATION_MODE == "L1":
                    from strategy.marginal_livestock_valuator import derive_opponent_committed_livestock_supply
                    opp_livestock_supply = derive_opponent_committed_livestock_supply(opp_farm, day, scenario="BASE")
                elif LIVESTOCK_VALUATION_MODE in ("L2", "L2A", "L2B", "L2C"):
                    from strategy.marginal_livestock_valuator import derive_opponent_committed_livestock_stress_capacity
                    opp_stress_supply = derive_opponent_committed_livestock_stress_capacity(opp_farm, day)
        except Exception:
            opp_livestock_supply = None
            opp_stress_supply = None

        # ---------------- phase gating ---------------------------------
        is_endgame = day >= ENDGAME_START_DAY
        if is_endgame:
            plan.phase = "endgame"
            plan.watering_enabled = False
            # feeding active on Day 28 (produces at EOD → sellable on Day 29);
            # disabled on Day 29 (produces after season scoring, wastes wheat)
            plan.feeding_enabled = day < ANIMAL_FEED_CUTOFF_DAY
            plan.notes.append("endgame: liquidation mode")
        else:
            plan.phase = ("phase1_wheat_cash" if day <= 4 else
                          "phase2_scaling" if day <= 15 else
                          "phase3_market_exploitation")

        animals = [t for t in farm.iter_tiles() if t.is_animal]
        n_animals = len(animals)
        empty_tiles = [t.pos for t in farm.iter_tiles()
                       if t.kind == "EMPTY" and
                       farm.quadrant_of(t.pos) in farm.unlocked and
                       t.pos != PORT_SW]

        # --- Authoritative wheat feed capacity projection ---
        wheat_tiles = [t for t in farm.iter_tiles()
                       if t.is_plant and t.crop == "WHEAT"]
        wheat_tile_days = [getattr(t, "planted_day", None) for t in wheat_tiles]
        days_left = SEASON_DAYS - day
        wheat_cap = compute_wheat_capacity(wheat_tile_days, day)
        wheat_have = int(private.shed.get("WHEAT", 0))

        feed_info = compute_authoritative_feed_capacity(
            farm, private, day, season_end=28, current_animals_count=n_animals)
        projected_feed_supply = feed_info["projected_wheat_supply"]
        feeding_days_left = feed_info["feeding_days_left"]
        sustainable = feed_info["sustainable_herd_size"]

        # --- wheat deficit detection ---
        deficit, trigger = detect_wheat_deficit(
            wheat_cap, wheat_have, days_left,
            n_animals, FEED_WHEAT_BUFFER_DAYS)

        # ---------------- animal expansion (dynamic 5-constraint optimizer) ------
        counts = {}
        for t in animals:
            counts[t.animal] = counts.get(t.animal, 0) + 1
        for a in ANIMAL_LIST:
            counts[a] = counts.get(a, 0) + int(private.shed.get(a, 0))
        for inv in private.inventories:
            for a in ANIMAL_LIST:
                counts[a] = counts.get(a, 0) + int(inv.get(a, 0))
        structures_empty = {t.pos: t.kind for t in farm.iter_tiles()
                            if t.kind in ("COOP", "PASTURE") and not t.is_animal}

        buy_animal = {}
        buy_wheat = 0
        reserved_structure_tiles = []
        EFFECTIVE_ACTIONS_PER_UNIT = 18

        # Target hands from hiring schedule
        target_hands = get_target_hands(day)
        current_hands = len(farm.hands)
        hires = max(0, target_hands - current_hands)

        # Dynamic animal targets computation (Dynamic Near-Shed Pasture Planner)
        committed_counts = get_committed_crop_counts(farm)
        crop_opp_val, best_crop_name = estimate_crop_opportunity_value(
            day=day,
            forecast=self.fc,
            boosts=boosts,
            committed_counts=committed_counts,
            crop_score_func=_crop_score,
            crop_allowed_func=_crop_allowed_today,
            n_animals=n_animals,
            opp_advice=opp_advice,
        )

        try:
            from config import get_active_livestock_caps, LIVESTOCK_OVERRIDE_ENABLED
            active_caps = get_active_livestock_caps()
            use_override = LIVESTOCK_OVERRIDE_ENABLED
        except Exception:
            active_caps = {}
            use_override = False

        pasture_eval = evaluate_pasture_candidates(
            farm=farm,
            day=day,
            empty_tiles=list(empty_tiles),
            current_animals=counts,
            crop_opportunity_val=crop_opp_val,
            crop_name=best_crop_name,
            cutoff_day=C4_LIVESTOCK_CUTOFF_DAY,
            cow_cap=active_caps.get("COW"),
            sheep_cap=active_caps.get("SHEEP"),
            herd_cap=active_caps.get("HERD"),
        )
        existing_pastures = pasture_eval["existing_pastures"]
        existing_empty_pastures = pasture_eval["existing_empty_pastures"]
        dynamic_max_pastures = pasture_eval["dynamic_max_pastures"]
        positive_pasture_cands = list(pasture_eval["positive_candidates"])
        max_pastures = dynamic_max_pastures

        # Discretionary cash reservation: wages, base reserve, and upcoming land/seed escrow
        future_hire_cost = sum(hire_total_cost(get_target_hands(d))
                               for d in range(day, min(day + 3, 30)))
        n_extra_temp = len(farm.unlocked) - 1
        next_q_temp = n_extra_temp + 2 if n_extra_temp + 2 <= 4 else None
        seed_reserve = 0
        land_reserve = 0

        try:
            from config import SW_OWNERSHIP_MODE
            use_experiment_sw = (SW_OWNERSHIP_MODE in ("early_liquidity", "pure_economic"))
        except Exception:
            use_experiment_sw = False

        if next_q_temp == 3 and "SW" not in farm.unlocked and day <= LAND_BUY_LAST_DAY:
            if use_experiment_sw:
                # Near-term land shadow reserve:
                # Protect SW money ONLY when SW is plausibly reachable within the next 24 turns
                # based on current cash plus conservative near-term inflows.
                # Never suppress profitable cows/sheep on Days 5-8 if SW is not yet reachable.
                if day >= 7:
                    try:
                        from strategy.expansion_planner import compute_conservative_inflows_before_hire
                        inflows_24h = compute_conservative_inflows_before_hire(farm, private)
                    except Exception:
                        inflows_24h = 0.0

                    potential_cash_24h = float(ctx["farm"].money) + inflows_24h
                    near_term_obligations = future_hire_cost + self.reserve
                    if potential_cash_24h >= 2000.0 + near_term_obligations:
                        # Plausibly reachable: protect SW money up to $2,000 from current cash after obligations
                        land_reserve = min(2000.0, max(0.0, float(ctx["farm"].money) - near_term_obligations))
                    else:
                        land_reserve = 0.0
                else:
                    land_reserve = 0.0
                seed_reserve = 0.0
            else:
                if day in (8, 9) and ctx["farm"].money >= 2000:
                    land_reserve = 2000
                    seed_reserve = 150
                elif day >= 11:
                    land_reserve = 2000
                    seed_reserve = 150
        elif next_q_temp == 2 and "NE" not in farm.unlocked and 3 <= day <= LAND_BUY_LAST_DAY:
            if ctx["farm"].money >= 1000:
                land_reserve = 1000

        try:
            from config import BOOTSTRAP_LIVESTOCK_ARM
        except Exception:
            BOOTSTRAP_LIVESTOCK_ARM = "none"

        if day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None):
            # Stage 2: Mandatory Day-0 Crop Floor (4 Melon + 4 Wheat = $360) across Arms B, C, D, E
            day_0_seed_reserve = 360.0
            ne_fund_reserve = 0
            day_0_hire_cost = 7.0  # Day 0 mandatory hires (4 hands)
            cash_for_animals = max(0.0, ctx["farm"].money - day_0_hire_cost - self.reserve - seed_reserve - land_reserve - day_0_seed_reserve - ne_fund_reserve)
        else:
            day_0_seed_reserve = 1040 if day == 0 else 0
            ne_fund_reserve = 600 if "NE" not in farm.unlocked and day < 3 else 0
            cash_for_animals = max(0.0, ctx["farm"].money - future_hire_cost - self.reserve - seed_reserve - land_reserve - day_0_seed_reserve - ne_fund_reserve)

        ne_locked = bool("NE" not in farm.unlocked) if (farm and hasattr(farm, "unlocked")) else False
        try:
            from config import get_point2_pre_ne_capital_mode
            pre_ne_mode = get_point2_pre_ne_capital_mode()
        except Exception:
            pre_ne_mode = "off"

        farm_money_avail = float(ctx["farm"].money) if (ctx.get("farm") and hasattr(ctx["farm"], "money")) else (
            float(ctx["farm"].get("money", 0.0)) if isinstance(ctx.get("farm"), dict) else 0.0
        )
        if ne_locked and pre_ne_mode in ("ne_first", "ne_escrow"):
            if pre_ne_mode == "ne_first":
                pre_ne_livestock_envelope = 0.0
                cash_for_animals = 0.0
            else:
                mand_hire = day_0_hire_cost if (day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None)) else future_hire_cost
                mand_seed = day_0_seed_reserve if (day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None)) else seed_reserve
                pre_ne_nonlivestock_holds = mand_hire + self.reserve + mand_seed
                ne_land_hold = 1000.0
                pre_ne_livestock_envelope = max(0.0, farm_money_avail - pre_ne_nonlivestock_holds - ne_land_hold)
                cash_for_animals = pre_ne_livestock_envelope
        else:
            pre_ne_livestock_envelope = None

        # Dynamic animal targets via corrected Astra heuristic
        # Stage 8B C4: Cease new livestock investment on or after C4_LIVESTOCK_CUTOFF_DAY (Day 12).
        # Days 3-5: Protect NE land fund ($1,000) and workforce ramp.
        allow_livestock = (day < C4_LIVESTOCK_CUTOFF_DAY)
        try:
            from config import SELECTIVE_LIVESTOCK_GATE_ENABLED, SELECTIVE_LIVESTOCK_MAX_DAY
            if not allow_livestock and SELECTIVE_LIVESTOCK_GATE_ENABLED and day <= SELECTIVE_LIVESTOCK_MAX_DAY:
                allow_livestock = True
        except ImportError:
            pass

        try:
            from config import LIVESTOCK_EXPERIMENT_ARM
        except ImportError:
            LIVESTOCK_EXPERIMENT_ARM = "ArmA"

        planning_feed_ledger = None
        herd_plan = None

        if LIVESTOCK_EXPERIMENT_ARM == "ArmC":
            if is_endgame or not allow_livestock:
                dynamic_targets = {"COW": counts.get("COW", 0),
                                   "SHEEP": counts.get("SHEEP", 0),
                                   "GOOSE": 0}
                target_pastures = counts.get("COW", 0) + counts.get("SHEEP", 0)
                needed_new_pastures = 0
                requested_herd_size = sum(dynamic_targets.values())
                final_feed_capped_herd_size = min(requested_herd_size, sustainable)
            else:
                from strategy.herd_planner import generate_dynamic_herd_plan, get_forward_housing_demand
                point2_mode = get_point2_feed_mode() if callable(get_point2_feed_mode) else "off"
                ledger_build_error = None
                if point2_mode in ("herd_plan", "live"):
                    if build_feed_resource_ledger is None:
                        ledger_build_error = RuntimeError("build_feed_resource_ledger is not available")
                    else:
                        try:
                            farm_money = float(ctx["farm"].money) if (ctx.get("farm") and hasattr(ctx["farm"], "money")) else (
                                float(ctx["farm"].get("money", 0.0)) if isinstance(ctx.get("farm"), dict) else 0.0
                            )
                            planning_nonanimal_hold = max(0.0, farm_money - float(cash_for_animals))
                            planning_feed_ledger = build_feed_resource_ledger(
                                ctx,
                                hard_cash_hold=planning_nonanimal_hold,
                                strategic_cash_hold=0.0,
                                horizon_days=4,
                                lifetime_price_policy="engine_stress_bound_v1",
                                market_inventory=market_inv,
                                town_shops=town_shops,
                                opponent_farm=ctx.get("opponent_farm") if isinstance(ctx, dict) else getattr(ctx, "opponent_farm", None),
                            )
                            if planning_feed_ledger is None:
                                ledger_build_error = RuntimeError("build_feed_resource_ledger returned None")
                        except Exception as e:
                            planning_feed_ledger = None
                            ledger_build_error = e

                if point2_mode in ("herd_plan", "live") and ledger_build_error is not None:
                    dynamic_targets = {
                        "COW": counts.get("COW", 0),
                        "SHEEP": counts.get("SHEEP", 0),
                        "GOOSE": 0,
                    }
                    target_pastures = counts.get("COW", 0) + counts.get("SHEEP", 0)
                    needed_new_pastures = 0
                    requested_herd_size = sum(dynamic_targets.values())
                    final_feed_capped_herd_size = requested_herd_size
                    plan.diagnostics["point2_feed_authority"] = {
                        "mode": point2_mode,
                        "feed_authority": "ledger_error_fail_closed",
                        "error_type": type(ledger_build_error).__name__,
                        "error_message": str(ledger_build_error),
                    }
                else:
                    try:
                        is_late_selective = False
                        phys_housing_cap = None
                        allow_late_continuation = False
                        if point2_mode == "live" and day >= C4_LIVESTOCK_CUTOFF_DAY and allow_livestock:
                            is_late_selective = True
                            obs_empty_pastures = sum(
                                1 for t in farm.iter_tiles()
                                if getattr(t, "kind", None) == "PASTURE" and not getattr(t, "is_animal", False)
                                and (farm.quadrant_of(t.pos) in farm.unlocked if hasattr(farm, "quadrant_of") else True)
                            ) if farm and hasattr(farm, "iter_tiles") else 0
                            obs_empty_coops = sum(
                                1 for t in farm.iter_tiles()
                                if getattr(t, "kind", None) == "COOP" and not getattr(t, "is_animal", False)
                                and (farm.quadrant_of(t.pos) in farm.unlocked if hasattr(farm, "quadrant_of") else True)
                            ) if farm and hasattr(farm, "iter_tiles") else 0

                            unplaced_large = (
                                sum(int(private.shed.get(a, 0)) for a in ("COW", "SHEEP")) if private and hasattr(private, "shed") else 0
                            ) + (
                                sum(sum(int(inv.get(a, 0)) for a in ("COW", "SHEEP")) for inv in private.inventories) if private and hasattr(private, "inventories") else 0
                            )
                            unplaced_small = (
                                int(private.shed.get("GOOSE", 0)) if private and hasattr(private, "shed") else 0
                            ) + (
                                sum(int(inv.get("GOOSE", 0)) for inv in private.inventories) if private and hasattr(private, "inventories") else 0
                            )
                            effective_empty_pastures = max(0, obs_empty_pastures - unplaced_large)
                            phys_housing_cap = {
                                "PASTURE": effective_empty_pastures,
                                "COOP": max(0, obs_empty_coops - unplaced_small),
                            }

                            try:
                                from config import get_one_at_a_time_late_housing_enabled
                                late_cont_enabled = get_one_at_a_time_late_housing_enabled()
                            except Exception:
                                late_cont_enabled = False

                            if late_cont_enabled and day in (12, 13):
                                # Check if a late continuation pasture is already in flight
                                mem = ctx.get("memory") if isinstance(ctx, dict) else None
                                in_flight = False
                                target_tile = None
                                if mem:
                                    in_flight = bool(mem.get("late_continuation_in_flight", False))
                                    target_tile = mem.get("late_continuation_target_pos")
                                else:
                                    try:
                                        from state.state_tracker import _STATE
                                        in_flight = bool(_STATE.get("late_continuation_in_flight", False))
                                        target_tile = _STATE.get("late_continuation_target_pos")
                                    except Exception:
                                        in_flight = False

                                # If target tile has become a physical pasture, in-flight is complete!
                                if target_tile and farm:
                                    target_t = farm.tile_at(target_tile) if hasattr(farm, "tile_at") else None
                                    if target_t and getattr(target_t, "kind", None) == "PASTURE":
                                        in_flight = False
                                        if mem:
                                            mem["late_continuation_in_flight"] = False
                                            mem["late_continuation_target_pos"] = None
                                        try:
                                            from state.state_tracker import _STATE
                                            _STATE["late_continuation_in_flight"] = False
                                            _STATE["late_continuation_target_pos"] = None
                                        except Exception:
                                            pass
                                elif effective_empty_pastures > 0:
                                    in_flight = False
                                    if mem:
                                        mem["late_continuation_in_flight"] = False
                                        mem["late_continuation_target_pos"] = None
                                    try:
                                        from state.state_tracker import _STATE
                                        _STATE["late_continuation_in_flight"] = False
                                        _STATE["late_continuation_target_pos"] = None
                                    except Exception:
                                        pass

                                # One-at-a-time continuation is allowed strictly when zero empty pastures exist AND zero in flight
                                if effective_empty_pastures == 0 and not in_flight:
                                    allow_late_continuation = True

                        herd_plan = generate_dynamic_herd_plan(
                            day=day,
                            hour=hour,
                            current_herd=counts,
                            town_shops=town_shops,
                            market_inventory=market_inv,
                            max_sustainable=sustainable,
                            active_caps=active_caps,
                            crop_opportunity_val=crop_opp_val,
                            horizon_days=4,
                            opponent_committed_supplies=opp_livestock_supply,
                            opponent_stress_supplies=opp_stress_supply,
                            guard_threshold=guard_threshold,
                            feed_ledger=planning_feed_ledger,
                            late_selective_mode=is_late_selective,
                            physical_housing_capacity=phys_housing_cap,
                            allow_late_continuation=allow_late_continuation,
                            pre_ne_capital_mode=pre_ne_mode,
                            ne_locked=ne_locked,
                            pre_ne_livestock_envelope=pre_ne_livestock_envelope,
                        )
                        target_pastures = max(
                            herd_plan.required_pastures,
                            counts.get("COW", 0) + counts.get("SHEEP", 0)
                        )
                        dynamic_targets = dict(herd_plan.desired_herd)
                        housing_demand = get_forward_housing_demand(
                            herd_plan,
                            existing_pastures,
                            len(reserved_structure_tiles)
                        )
                        needed_new_pastures = housing_demand["needed_pastures"]
                        requested_herd_size = sum(dynamic_targets.values())
                        if herd_plan and getattr(herd_plan, "pre_ne_diagnostics", None):
                            plan.diagnostics["pre_ne_capital"] = dict(herd_plan.pre_ne_diagnostics)
                        if point2_mode in ("herd_plan", "live"):
                            final_feed_capped_herd_size = requested_herd_size
                            plan.diagnostics["point2_feed_authority"] = {
                                "mode": point2_mode,
                                "feed_authority": "ledger",
                                "final_feed_capped_herd_size": final_feed_capped_herd_size,
                                "legacy_sustainable_herd_size": sustainable,
                                "ledger_summary": planning_feed_ledger.to_dict() if planning_feed_ledger else None,
                                "feed_hold_diagnostics": planning_feed_ledger.get_feed_hold_diagnostics() if planning_feed_ledger else None,
                                "buy_animal_sequence": list(herd_plan.buy_animal_sequence) if herd_plan else [],
                                "provisional_candidates": list(herd_plan.provisional_candidates) if herd_plan else [],
                            }
                        else:
                            final_feed_capped_herd_size = min(requested_herd_size, sustainable)
                    except Exception as e:
                        if point2_mode in ("herd_plan", "live"):
                            dynamic_targets = {
                                "COW": counts.get("COW", 0),
                                "SHEEP": counts.get("SHEEP", 0),
                                "GOOSE": 0,
                            }
                            target_pastures = counts.get("COW", 0) + counts.get("SHEEP", 0)
                            needed_new_pastures = 0
                            requested_herd_size = sum(dynamic_targets.values())
                            final_feed_capped_herd_size = requested_herd_size
                            plan.diagnostics["point2_feed_authority"] = {
                                "mode": point2_mode,
                                "feed_authority": "ledger_error_fail_closed",
                                "error_type": type(e).__name__,
                                "error_message": str(e),
                            }
                        else:
                            raise e
        elif is_endgame or not allow_livestock or day in (3, 4, 5):
            dynamic_targets = {"COW": counts.get("COW", 0),
                               "SHEEP": counts.get("SHEEP", 0),
                               "GOOSE": 0}
            requested_herd_size = sum(dynamic_targets.values())
            final_feed_capped_herd_size = min(requested_herd_size, sustainable)
            target_pastures = max(
                dynamic_targets.get("COW", 0) + dynamic_targets.get("SHEEP", 0),
                counts.get("COW", 0) + counts.get("SHEEP", 0)
            )
            needed_new_pastures = max(0, target_pastures - existing_pastures)
        else:
            raw_targets = get_animal_targets(
                day=day,
                money=cash_for_animals,
                shed_wheat=wheat_have,
                current_animals=counts,
                max_pastures=max_pastures,
                max_sustainable=sustainable,
                cow_cap=active_caps.get("COW"),
                sheep_cap=active_caps.get("SHEEP"),
                herd_cap=active_caps.get("HERD"),
                town_shops=town_shops,
                market_inventory=market_inv,
            )
            requested_herd_size = sum(raw_targets.values())
            dynamic_targets = dict(raw_targets)
            if requested_herd_size > sustainable:
                excess = requested_herd_size - sustainable
                for an in ("GOOSE", "COW", "SHEEP"):
                    if excess <= 0:
                        break
                    reduce_by = min(excess, dynamic_targets.get(an, 0))
                    dynamic_targets[an] -= reduce_by
                    excess -= reduce_by
            final_feed_capped_herd_size = min(requested_herd_size, sustainable)
            target_pastures = max(
                dynamic_targets.get("COW", 0) + dynamic_targets.get("SHEEP", 0),
                counts.get("COW", 0) + counts.get("SHEEP", 0)
            )
            needed_new_pastures = max(0, target_pastures - existing_pastures)

        # Proactive infrastructure reservation (All Arms):
        # Enqueue near-shed pastures up to target_pastures (capped at 2 in queue, verified economically positive)
        existing_structs = existing_pastures + len(reserved_structure_tiles)

        # ArmC-Cell: Check if already-justified pasture demand should have location allocated in SW
        sw_cell_allocated_tiles = []
        try:
            from config import SW_CELL_HOUSING_ENABLED, SW_CELL_MAX_PASTURES
        except Exception:
            SW_CELL_HOUSING_ENABLED = False
            SW_CELL_MAX_PASTURES = 1

        if SW_CELL_HOUSING_ENABLED and "SW" in farm.unlocked and day < C4_LIVESTOCK_CUTOFF_DAY:
            existing_sw_pastures = sum(1 for t in farm.iter_tiles() if getattr(t, "kind", None) == "PASTURE" and farm.quadrant_of(t.pos) == "SW")
            reserved_sw_pastures = sum(1 for pos, _ in reserved_structure_tiles if farm.quadrant_of(pos) == "SW")
            needed_slots = max(0, target_pastures - (existing_pastures + len(reserved_structure_tiles)))
            if needed_slots > 0 and (existing_sw_pastures + reserved_sw_pastures) < SW_CELL_MAX_PASTURES:
                from strategy.sw_cell_allocator import allocate_sw_pasture_locations
                sw_locs, sw_diag = allocate_sw_pasture_locations(
                    farm=farm,
                    day=day,
                    needed_slots=needed_slots,
                    existing_sw_pastures=existing_sw_pastures,
                    reserved_sw_pastures=reserved_sw_pastures,
                    empty_tiles=list(empty_tiles),
                    reserved_crop_tiles=set(),
                    sw_cell_enabled=True,
                    max_sw_pastures=SW_CELL_MAX_PASTURES,
                )
                sw_cell_allocated_tiles = sw_locs
                plan.diagnostics["sw_cell_allocation"] = sw_diag

        # Cap pasture queue: 1 in-flight during late continuation on Days 12-13
        try:
            from config import BOOTSTRAP_LIVESTOCK_ARM, get_one_at_a_time_late_housing_enabled
            late_cont_enabled = get_one_at_a_time_late_housing_enabled()
        except Exception:
            BOOTSTRAP_LIVESTOCK_ARM = "none"
            late_cont_enabled = False

        if day in (12, 13) and late_cont_enabled and point2_mode == "live":
            max_pasture_queue = 1
        elif day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None):
            max_pasture_queue = max(2, target_pastures)
        else:
            max_pasture_queue = 2

        # ONE Authoritative Reservation Budget:
        # 1. Allocate justified SW cell pasture location if approved
        for sw_tile in sw_cell_allocated_tiles:
            if existing_structs < target_pastures and len(reserved_structure_tiles) < max_pasture_queue:
                reserved_structure_tiles.append((sw_tile, "BUILD_PASTURE"))
                existing_structs += 1
                positive_pasture_cands = [c for c in positive_pasture_cands if c["pos"] != sw_tile]

        # 2. Allocate remaining justified slots through existing NW/NE candidate path
        while existing_structs < target_pastures and len(reserved_structure_tiles) < max_pasture_queue and positive_pasture_cands:
            cand_info = positive_pasture_cands.pop(0)
            cand_pos = cand_info["pos"]
            reserved_structure_tiles.append((cand_pos, "BUILD_PASTURE"))
            existing_structs += 1

        # 3. Fallback slot allocation if positive_pasture_cands empty but target_pastures justified
        if existing_structs < target_pastures and len(reserved_structure_tiles) < max_pasture_queue:
            reserved_pos_set = {pos for pos, _ in reserved_structure_tiles}
            valid_empty = [
                t.pos for t in farm.iter_tiles()
                if not getattr(t, "is_plant", False) and not getattr(t, "is_animal", False)
                and getattr(t, "kind", "") not in ("PASTURE", "COOP", "ROCK", "RIVER")
                and farm.quadrant_of(t.pos) in farm.unlocked
                and farm.quadrant_of(t.pos) != "SE"
                and t.pos not in set(SHED_ACCESS_TILES)
                and t.pos not in reserved_pos_set
            ]
            if valid_empty:
                best_empty = min(valid_empty, key=lambda p: min(abs(p[0] - s[0]) + abs(p[1] - s[1]) for s in SHED_ACCESS_TILES))
                reserved_structure_tiles.append((best_empty, "BUILD_PASTURE"))
                existing_structs += 1

        # Record in-flight continuation state if a pasture was enqueued during Days 12-13
        if reserved_structure_tiles and day in (12, 13) and late_cont_enabled and point2_mode == "live":
            enqueued_pos = reserved_structure_tiles[0][0]
            mem = ctx.get("memory") if isinstance(ctx, dict) else None
            if mem:
                mem["late_continuation_in_flight"] = True
                mem["late_continuation_target_pos"] = enqueued_pos
                mem["late_continuation_max_in_flight"] = max(mem.get("late_continuation_max_in_flight", 0), 1)
            try:
                from state.state_tracker import _STATE
                _STATE["late_continuation_in_flight"] = True
                _STATE["late_continuation_target_pos"] = enqueued_pos
                _STATE["late_continuation_max_in_flight"] = max(_STATE.get("late_continuation_max_in_flight", 0), 1)
            except Exception:
                pass

        total_pastures = existing_pastures + len(reserved_structure_tiles)

        # Purchase affordable animals if empty pasture exists or is being built
        # Prioritize Sheep ($200/wool, $100 fert) and Cow ($160/milk, $100 fert); Zero Geese unless empty coop pre-exists
        # Stage 8B C4: Cap animal purchases and pasture construction on or after C4_LIVESTOCK_CUTOFF_DAY
        if not is_endgame and allow_livestock:
            if LIVESTOCK_EXPERIMENT_ARM == "ArmC":
                # Arm C: Fully dynamic shop-conditioned live purchase execution with transactional shadow state
                shadow_counts = dict(counts)
                shadow_cash = float(cash_for_animals)
                shadow_buy_animal = {}
                shadow_structures_empty = dict(structures_empty)

                base_orders = 4  # conservative reserve for hire, land, seeds, wheat
                consecutive_eval_seq = []

                try:
                    from config import get_p13_livestock_cap_enabled
                    use_livestock_cap = bool(get_p13_livestock_cap_enabled())
                except Exception:
                    use_livestock_cap = False

                working_feed_ledger = None
                existing_herd_ok = True
                if use_livestock_cap and build_feed_resource_ledger is not None:
                    try:
                        strategic_hold = float(hire_cost) + (float(land_cost) if buy_land else 0.0)
                        working_feed_ledger = build_feed_resource_ledger(
                            ctx,
                            hard_cash_hold=float(self.reserve),
                            strategic_cash_hold=strategic_hold,
                            horizon_days=4,
                        )
                        if evaluate_existing_herd_feasibility is not None:
                            existing_herd_ok, _ = evaluate_existing_herd_feasibility(working_feed_ledger)
                        else:
                            existing_herd_ok = True
                    except Exception:
                        working_feed_ledger = None
                        existing_herd_ok = True

                while True:
                    total_herd = sum(shadow_counts.values()) + sum(shadow_buy_animal.values())
                    eff_cap = min(active_caps.get("HERD", 20), int(max_pastures), max(0, int(sustainable)))
                    if total_herd >= eff_cap:
                        break
                    if feeding_days_left > 0 and (total_herd + 1) * feeding_days_left > projected_feed_supply:
                        break
                    if day > 14:
                        break
                    if day in (3, 4, 5):
                        # Protect NE unlock and early workforce ramp
                        break

                    threshold = 500.0 if day >= 12 else 0.0

                    cands_eval = {}
                    current_herd_combined = {
                        sp: shadow_counts.get(sp, 0) + shadow_buy_animal.get(sp, 0)
                        for sp in ("COW", "SHEEP", "GOOSE")
                    }
                    pasture_herd = current_herd_combined.get("COW", 0) + current_herd_combined.get("SHEEP", 0)

                    for sp in ("COW", "SHEEP", "GOOSE"):
                        curr_sp = current_herd_combined.get(sp, 0)
                        if sp == "COW" and curr_sp >= active_caps.get("COW", 19):
                            continue
                        if sp == "SHEEP" and curr_sp >= active_caps.get("SHEEP", 12):
                            continue
                        if sp == "GOOSE" and curr_sp >= 20:
                            continue

                        # Strict Housing Check
                        if sp in ("COW", "SHEEP"):
                            if day >= 12:
                                # Day 12–14 selective purchases: physically built + currently empty + unreserved housing only;
                                # planned/queued/future housing gives zero late-purchase credit.
                                physically_available = existing_pastures - pasture_herd
                                if physically_available <= 0:
                                    continue
                            else:
                                # Before Day 12: use existing production housing rules (existing + queued)
                                if pasture_herd >= total_pastures:
                                    continue
                        else:  # GOOSE
                            free_coop = [p for p, k in shadow_structures_empty.items() if k == "COOP"]
                            if not free_coop:
                                continue

                        cost = ANIMALS[sp]["cost"]
                        feed_reserve = 25.0 * max(
                            0, min(FEED_WHEAT_BUFFER_DAYS, days_left) * (total_herd + 1) - wheat_have
                        )
                        if shadow_cash < (cost + feed_reserve):
                            continue

                        if use_livestock_cap:
                            def _record_cap_rejection(reason_code):
                                shed_w = int((getattr(private, "shed", {}) or {}).get("WHEAT", 0)) if private else 0
                                plan.diagnostics.setdefault("p13_livestock_cap_rejections", []).append({
                                    "day": int(day),
                                    "hour": int(hour),
                                    "species": sp,
                                    "reason": reason_code,
                                    "herd_size": dict(current_herd_combined),
                                    "wheat_reserve": shed_w,
                                    "cash_reserve": float(getattr(farm, "money", 0.0)),
                                    "shadow_cash": float(shadow_cash),
                                    "usable_labor": float(usable_ap) if "usable_ap" in locals() else None,
                                    "core_workload": float(crop_wl) if "crop_wl" in locals() else None,
                                })

                            # 1. Existing feed-feasibility ledger evaluation
                            if working_feed_ledger is not None:
                                if not working_feed_ledger.baseline_feasible:
                                    _record_cap_rejection("existing_herd_infeasible")
                                    continue
                                cand_feed_res = evaluate_incremental_candidate(working_feed_ledger, sp, purchase_cost=cost)
                                if not cand_feed_res.feasible:
                                    _record_cap_rejection(cand_feed_res.blocking_reason)
                                    continue

                            # 2. Starvation & spatial feeding deadline check
                            from strategy.land_serviceability_model import (
                                _t_field,
                                _t_pos,
                                get_animal_daily_workload,
                                compute_herd_daily_workload,
                                compute_survival_feasibility_reservation,
                                compute_daily_labor_capacity,
                                compute_existing_workload,
                            )
                            has_starving_animal = any(
                                int(_t_field(t, "consecutive_unfed", 0)) >= 1
                                for t in farm.iter_tiles()
                                if _t_field(t, "is_animal") or _t_field(t, "animal")
                            )
                            if has_starving_animal:
                                _record_cap_rejection("recent_animal_starvation")
                                continue

                            surv_res = compute_survival_feasibility_reservation(farm, day, hour=hour)
                            if not surv_res.get("is_deadline_feasible", True):
                                _record_cap_rejection("feeding_deadline_infeasible")
                                continue

                            # 3. Continuous labor headroom for herd maintenance
                            labor_cap = compute_daily_labor_capacity(day, farm=farm, hour=hour)
                            usable_ap = labor_cap["usable_effective_actions"]
                            crop_wl = compute_existing_workload(farm, day, include_animal_feeding=False)["total_existing_workload"]
                            current_herd_wl = compute_herd_daily_workload(current_herd_combined)
                            inc_wl = get_animal_daily_workload(sp)

                            sw_crops = sum(
                                1 for t in farm.iter_tiles()
                                if farm.quadrant_of(_t_pos(t)) == "SW"
                                and bool(_t_field(t, "is_plant", False) or _t_field(t, "kind") == "PLANT")
                            )
                            sw_crop_wl = round(sw_crops * 1.3, 1)

                            if (crop_wl + sw_crop_wl + current_herd_wl + inc_wl) > usable_ap:
                                _record_cap_rejection("insufficient_labor_for_herd")
                                continue

                            # 4. Core crop survival health
                            core_workload = compute_existing_workload(farm, day, include_animal_feeding=False)
                            if core_workload.get("survival_water_count", 0) > 0:
                                _record_cap_rejection("core_crop_survival_debt")
                                continue

                        opp_cand_supply = (
                            opp_livestock_supply.get(ANIMALS[sp]["product"])
                            if opp_livestock_supply else None
                        )
                        eval_res = estimate_realized_marginal_animal_value(
                            species=sp,
                            day=day,
                            current_animals=current_herd_combined,
                            empty_pastures=max(0, existing_pastures - pasture_herd),
                            town_shops=town_shops,
                            market_inventory=market_inv,
                            opponent_committed_supply=opp_cand_supply,
                        )
                        cands_eval[sp] = {
                            "eval": eval_res,
                            "cost": cost,
                            "feed_reserve": feed_reserve,
                        }
                        if opp_stress_supply is not None:
                            opp_cand_stress = opp_stress_supply.get(ANIMALS[sp]["product"])
                            eval_stress = estimate_realized_marginal_animal_value(
                                species=sp,
                                day=day,
                                current_animals=current_herd_combined,
                                empty_pastures=max(0, existing_pastures - pasture_herd),
                                town_shops=town_shops,
                                market_inventory=market_inv,
                                opponent_committed_supply=opp_cand_stress,
                            )
                            cands_eval[sp]["stress_eval"] = eval_stress

                    if not cands_eval:
                        break

                    guard_diag = None
                    if opp_stress_supply is not None and select_guarded_livestock_candidate is not None:
                        base_evals = {s: cands_eval[s]["eval"] for s in cands_eval}
                        stress_evals = {s: cands_eval[s]["stress_eval"] for s in cands_eval}
                        best_sp, chosen_eval, guard_diag = select_guarded_livestock_candidate(
                            base_evals, stress_evals, guard_threshold=guard_threshold
                        )
                        best_cand = cands_eval[best_sp]
                        best_val = chosen_eval["net_realized_value"]
                        if guard_diag.get("switched"):
                            consecutive_eval_seq.append(
                                f"[GUARD_SWITCH: {guard_diag['baseline_best']}->{best_sp} gap={guard_diag.get('baseline_gap', 0.0):.1f}%]"
                            )
                    else:
                        best_sp = max(cands_eval.keys(), key=lambda s: cands_eval[s]["eval"]["net_realized_value"])
                        best_cand = cands_eval[best_sp]
                        best_val = best_cand["eval"]["net_realized_value"]

                    curr_num = current_herd_combined.get(best_sp, 0) + 1

                    if best_val < threshold:
                        consecutive_eval_seq.append(f"{best_sp} #{curr_num}: ${best_val:.0f} -> STOP (threshold ${threshold:.0f})")
                        _log_livestock_decision(day, hour, town_shops, current_herd_combined, cands_eval, selected=None, reason=f"below_threshold_{best_val:.0f}<{threshold:.0f}", guard_diag=guard_diag)
                        break

                    new_buy_animal = dict(shadow_buy_animal)
                    new_buy_animal[best_sp] = new_buy_animal.get(best_sp, 0) + 1
                    if (base_orders + len(new_buy_animal)) > 9:
                        consecutive_eval_seq.append(f"{best_sp} #{curr_num}: ${best_val:.0f} -> STOP (order cap)")
                        _log_livestock_decision(day, hour, town_shops, current_herd_combined, cands_eval, selected=None, reason="order_cap_reached", guard_diag=guard_diag)
                        break

                    # ACCEPTED: Update transactional shadow state
                    consecutive_eval_seq.append(f"{best_sp} #{curr_num}: +${best_val:.0f}")
                    accept_reason = "accepted"
                    if guard_diag and guard_diag.get("switched"):
                        accept_reason = f"accepted_guard_switch_{guard_diag['baseline_best']}_to_{best_sp}"
                    _log_livestock_decision(day, hour, town_shops, current_herd_combined, cands_eval, selected=best_sp, reason=accept_reason, guard_diag=guard_diag)

                    if use_livestock_cap and working_feed_ledger is not None:
                        try:
                            best_commit_res = evaluate_incremental_candidate(working_feed_ledger, best_sp, purchase_cost=best_cand["cost"])
                            if best_commit_res.feasible:
                                commit_candidate_reservation(working_feed_ledger, best_commit_res)
                        except Exception:
                            pass

                    shadow_buy_animal[best_sp] = shadow_buy_animal.get(best_sp, 0) + 1
                    shadow_cash -= best_cand["cost"]
                    if best_sp in ("COW", "SHEEP"):
                        free_p = [p for p, k in shadow_structures_empty.items() if k == "PASTURE"]
                        if free_p:
                            del shadow_structures_empty[free_p[0]]
                    elif best_sp == "GOOSE":
                        free_c = [p for p, k in shadow_structures_empty.items() if k == "COOP"]
                        if free_c:
                            del shadow_structures_empty[free_c[0]]

                buy_animal = shadow_buy_animal
                cash_for_animals = shadow_cash
                dynamic_targets = {
                    sp: counts.get(sp, 0) + buy_animal.get(sp, 0)
                    for sp in ("COW", "SHEEP", "GOOSE")
                }
                if consecutive_eval_seq:
                    plan.notes.append(f"ArmC sequence: {'; '.join(consecutive_eval_seq)}")
            else:
                # Arm A & Arm B: target-oriented structure
                animals_owned_or_buying = sum(counts.values()) + sum(buy_animal.values())
                housing_available = max(0, total_pastures - animals_owned_or_buying)

                if LIVESTOCK_EXPERIMENT_ARM == "ArmB":
                    if opp_stress_supply is not None and select_guarded_livestock_candidate is not None:
                        opp_m_stress = opp_stress_supply.get("MILK")
                        opp_w_stress = opp_stress_supply.get("WOOL")
                        base_c = estimate_realized_marginal_animal_value("COW", day, counts, town_shops=town_shops, market_inventory=market_inv)
                        base_s = estimate_realized_marginal_animal_value("SHEEP", day, counts, town_shops=town_shops, market_inventory=market_inv)
                        stress_c = estimate_realized_marginal_animal_value("COW", day, counts, town_shops=town_shops, market_inventory=market_inv, opponent_committed_supply=opp_m_stress)
                        stress_s = estimate_realized_marginal_animal_value("SHEEP", day, counts, town_shops=town_shops, market_inventory=market_inv, opponent_committed_supply=opp_w_stress)
                        best_sp, _, _ = select_guarded_livestock_candidate(
                            {"COW": base_c, "SHEEP": base_s},
                            {"COW": stress_c, "SHEEP": stress_s},
                            guard_threshold=guard_threshold,
                        )
                        if best_sp == "COW":
                            species_order = ("COW", "SHEEP", "GOOSE")
                        else:
                            species_order = ("SHEEP", "COW", "GOOSE")
                    else:
                        opp_m = opp_livestock_supply.get("MILK") if opp_livestock_supply else None
                        opp_w = opp_livestock_supply.get("WOOL") if opp_livestock_supply else None
                        eval_c = estimate_realized_marginal_animal_value("COW", day, counts, town_shops=town_shops, market_inventory=market_inv, opponent_committed_supply=opp_m)
                        eval_s = estimate_realized_marginal_animal_value("SHEEP", day, counts, town_shops=town_shops, market_inventory=market_inv, opponent_committed_supply=opp_w)
                        if eval_c["net_realized_value"] > eval_s["net_realized_value"]:
                            species_order = ("COW", "SHEEP", "GOOSE")
                        else:
                            species_order = ("SHEEP", "COW", "GOOSE")
                else:
                    species_order = sorted(
                        ["COW", "SHEEP"],
                        key=lambda an: (dynamic_targets.get(an, 0) - counts.get(an, 0), 1 if an == "COW" else 0),
                        reverse=True
                    ) + ["GOOSE"] if use_override else ("SHEEP", "COW", "GOOSE")

                for animal in species_order:
                    target = dynamic_targets.get(animal, 0)
                    info = ANIMALS[animal]
                    struct_kind = info["structure"]
                    free_struct = [pos for pos, k in structures_empty.items() if k == struct_kind]
                    while (housing_available > 0 and (counts.get(animal, 0) + buy_animal.get(animal, 0) < target)) or (animal == "GOOSE" and free_struct):
                        total_now = sum(counts.values()) + sum(buy_animal.values())
                        if total_now >= sustainable:
                            break
                        if feeding_days_left > 0 and (total_now + 1) * feeding_days_left > projected_feed_supply:
                            break
                        if cash_for_animals >= info["cost"]:
                            buy_animal[animal] = buy_animal.get(animal, 0) + 1
                            cash_for_animals -= info["cost"]
                            if free_struct:
                                del structures_empty[free_struct[0]]
                                free_struct.pop(0)
                            housing_available = max(0, housing_available - 1)
                        else:
                            break


            # Maintain feed wheat buffer
            total_animals_planned = sum(counts.values()) + sum(buy_animal.values())
            if total_animals_planned > 0:
                try:
                    from config import BOOTSTRAP_LIVESTOCK_ARM
                except Exception:
                    BOOTSTRAP_LIVESTOCK_ARM = "none"
                eff_planned = min(2, total_animals_planned) if (day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None)) else total_animals_planned
                needed_wheat = eff_planned * min(FEED_WHEAT_BUFFER_DAYS, days_left)
                if needed_wheat > wheat_have:
                    buy_wheat = needed_wheat - wheat_have
        else:
            total_animals_planned = sum(counts.values())

        # Expose authoritative feed sustainability diagnostics
        projected_feed_demand = total_animals_planned * feeding_days_left

        # Compute authoritative feed risk metadata for CentralPlanner arbitration
        immediate_shortage = (n_animals > 0 and wheat_have < n_animals)
        next_wheat_harvest_day = None
        wheat_tiles = [t for t in farm.iter_tiles() if getattr(t, "is_plant", False) and getattr(t, "crop", None) == "WHEAT"]
        for t in wheat_tiles:
            planted_day = getattr(t, "planted_day", None)
            if planted_day is not None:
                matures = planted_day + CROPS["WHEAT"]["first_yield_day"]
                if matures >= day:
                    if next_wheat_harvest_day is None or matures < next_wheat_harvest_day:
                        next_wheat_harvest_day = matures

        feed_days_covered = (wheat_have // n_animals) if n_animals > 0 else 999
        replenishment_safe = (
            next_wheat_harvest_day is not None and
            next_wheat_harvest_day <= (day + feed_days_covered)
        )
        near_term_shortage = (
            n_animals > 0 and
            not immediate_shortage and
            feed_days_covered < 2 and
            not replenishment_safe
        )

        feed_risk = {
            "immediate_shortage": immediate_shortage,
            "near_term_shortage": near_term_shortage,
            "feed_days_covered": feed_days_covered,
            "next_safe_replenishment_day": next_wheat_harvest_day,
            "projected_deficit": deficit,
            "feed_trigger": trigger,
            "wheat_have": wheat_have,
            "n_animals": n_animals,
            "macro_buy_wheat_intent": int(buy_wheat),
            "projected_wheat_supply": projected_feed_supply,
        }

        plan.diagnostics.update({
            "projected_wheat_supply": projected_feed_supply,
            "projected_wheat_demand": projected_feed_demand,
            "sustainable_herd_size": sustainable,
            "requested_herd_size": requested_herd_size,
            "final_feed_capped_herd_size": final_feed_capped_herd_size,
            "feed_risk": feed_risk,
            "pasture_diagnostics": {
                "existing_pastures": existing_pastures,
                "existing_empty_pastures": existing_empty_pastures,
                "current_large_livestock": pasture_eval.get("current_large_livestock", 0),
                "unused_existing_pasture_capacity": pasture_eval.get("unused_existing_pasture_capacity", 0),
                "first_new_pasture_marginal_slot": pasture_eval.get("first_new_pasture_marginal_slot"),
                "current_animals": dict(counts),
                "animals_in_transit": sum(buy_animal.values()),
                "dynamic_pasture_candidates": pasture_eval["dynamic_candidates_count"],
                "positive_pasture_candidates": pasture_eval["positive_candidates_count"],
                "dynamic_max_pastures": dynamic_max_pastures,
                "feed_sustainable_cap": sustainable,
                "economic_herd_cap": HERD_CAP,
                "effective_herd_cap": min(HERD_CAP, dynamic_max_pastures, sustainable),
                "desired_target_herd": sum(dynamic_targets.values()),
                "pastures_needed_now": needed_new_pastures,
                "pastures_queued_now": len(reserved_structure_tiles),
                "crop_opportunity_value": crop_opp_val,
                "best_crop": best_crop_name,
                "evaluated_candidates": pasture_eval["all_candidates"],
            },
        })

        # structure build queue: use specific build_op
        if reserved_structure_tiles:
            plan.build_op = "BUILD_PASTURE"
            plan.build_queue = [t for t, _ in reserved_structure_tiles[:2]]

        # ---------------- crop queue on remaining tiles ----------------
        # Remove ONLY those tiles queued for structure construction today from crop queue.
        # Unqueued candidate tiles remain 100% available for agricultural planting.
        queued_build_positions = {pos for pos, _ in reserved_structure_tiles}
        empty_tiles = [pos for pos in empty_tiles if pos not in queued_build_positions]

        # endgame: no new planting — just harvest and sell
        plant_queue = []
        buy_seed = {}
        # ---- Budget prioritization (v5.10: with SW treasury protection) ----
        money = ctx["farm"].money
        hire_cost = hire_total_cost(hires)

        # --- v5.11: Expansion urgency + ROI + land decision ---
        n_extra_unlocked = len(farm.unlocked) - 1
        next_quadrant = n_extra_unlocked + 2 if n_extra_unlocked + 2 <= 4 else None
        sw_urgency = 0.0
        sw_reason = ""
        sw_info = {}
        land_roi = 0.0
        land_roi_info = {}
        ow_factor = 1.0
        buy_land = False
        land_cost = 0

        # Count own tiles for ROI calculation
        n_own_tiles = len([t for t in farm.iter_tiles() if t.is_plant])
        n_opp_tiles = 0  # opponent tiles not available in observation

        feed_shortfall_cost = 0.0
        feed_shortfall_units = 0
        proj_wheat_req = 0
        wheat_on_hand = 0
        land_capital_protection_active = False

        if not is_endgame and next_quadrant is not None:
            try:
                from config import get_quadrant_hard_block
                _qhb = get_quadrant_hard_block()
            except Exception:
                _qhb = QUADRANT_HARD_BLOCK
            if next_quadrant in _qhb:
                sw_reason = "hard_blocked"
            elif next_quadrant in QUADRANT_UNLOCK_DAYS:
                # Time-aware unavoidable feed shortfall for existing animals
                feed_buffer = 5 if day <= 5 and n_animals > 0 else FEED_WHEAT_BUFFER_DAYS
                wheat_on_hand, proj_wheat_req, feed_shortfall_units, feed_shortfall_cost = compute_unavoidable_feed_shortfall(
                    farm, private, day, n_animals, feed_buffer, ctx=ctx
                )

                # v5.11: Compute dynamic land ROI
                land_roi, land_roi_info = compute_land_roi(
                    next_quadrant, day, money, farm, self.fc,
                    n_own_tiles=n_own_tiles, n_opp_tiles=n_opp_tiles)

                # v5.11: Compute opportunity-window factor
                ow_factor = opportunity_window_factor(next_quadrant, day)
                adjusted_roi = land_roi * ow_factor

                # Labor serviceability check (Fix 1: compute_projected_workers)
                try:
                    from strategy.land_serviceability_model import compute_projected_workers
                    worker_count = compute_projected_workers(farm, day, money=money, hour=hour)
                except Exception:
                    worker_count = 1 + (len(farm.hands) if hasattr(farm, "hands") else 0)
                current_active_tiles = 0
                if hasattr(farm, "iter_tiles"):
                    current_active_tiles = sum(
                        1 for t in farm.iter_tiles()
                        if getattr(t, "is_plant", False) or getattr(t, "is_animal", False)
                    )
                labor_adequate = (worker_count >= 2) or (current_active_tiles < 15)

                # Compute urgency for deadline tracking (does NOT gate or loosen purchases)
                sw_urgency, _, _ = compute_land_urgency(
                    next_quadrant, day, money, farm)

                # Separate persistent land capital protection from deadline urgency
                protection_start_day = 5 if next_quadrant == 2 else (7 if next_quadrant == 3 else 999)
                is_early_ne = (next_quadrant == 2 and 3 <= day <= 6 and money >= 1000)
                land_capital_protection_active = (
                    next_quadrant is not None
                    and day >= protection_start_day
                    and day <= LAND_BUY_LAST_DAY
                    and (adjusted_roi > 0.0 or is_early_ne)
                    and labor_adequate
                    and next_quadrant not in _qhb
                )

                planned_animal_cost = sum(ANIMALS[a]["cost"] * k for a, k in buy_animal.items())

                # Use expansion planner's non-negotiable purchase gate
                # Charges ONLY mandatory hires + real unavoidable feed shortfall
                buy_land, sw_reason, sw_info = should_buy_land(
                    next_quadrant, day, money, farm,
                    hire_cost=hire_cost,
                    feed_cost=feed_shortfall_cost,
                    animal_cost=planned_animal_cost,
                    reserve=self.reserve,
                    roi=land_roi,
                    ow_factor=ow_factor,
                    forecast=self.fc,
                    seeds_owned=private.seeds,
                    wheat_on_hand=wheat_on_hand,
                    projected_wheat_requirement=proj_wheat_req,
                    actual_feed_shortfall_units=feed_shortfall_units,
                    urgency=sw_urgency,
                    treasury_protection_active=land_capital_protection_active,
                    is_purchase_hour=True,
                    already_committed_seed_cost=0.0,
                    private=private,
                    hour=hour,
                )
                if buy_land:
                    land_cost = LAND_PRICES[n_extra_unlocked]
                    land_capital_protection_active = False

                plan.diagnostics["land_decision"] = dict(sw_info)

        animal_cost = sum(ANIMALS[a]["cost"] * k for a, k in buy_animal.items())

        # Feed wheat buffer needed for existing + newly bought animals
        buy_wheat = 0
        effective_reserve = 50 if (day in (3, 4, 5, 6) and "NE" in farm.unlocked) else self.reserve
        post_hire_money = max(0.0, money - hire_cost)
        # Note: Land takes priority over discretionary animal purchases.
        available_before_seeds = max(0.0, post_hire_money - effective_reserve - land_cost)

        if plan.feeding_enabled:
            try:
                from config import get_p22a_day28_feed_harmonization_enabled
                p22a_enabled = bool(get_p22a_day28_feed_harmonization_enabled())
            except Exception:
                p22a_enabled = False

            if p22a_enabled and day == 28:
                # P2.2-A: Shared remaining feed obligation on Day 28
                # Calculate remaining feed requirement from animals that still need feeding today
                unfed_animals_today = sum(
                    1 for t in animals
                    if not getattr(t, "fed_today", False)
                )
                worker_wheat = sum(
                    int(inv.get("WHEAT", 0))
                    for inv in getattr(private, "inventories", [])
                ) if hasattr(private, "inventories") else 0
                accessible_wheat = wheat_have + worker_wheat
                wheat_needed = unfed_animals_today

                if accessible_wheat < wheat_needed:
                    deficit = wheat_needed - accessible_wheat
                    max_wheat_budget = max(0.0, available_before_seeds)
                    buy_wheat = min(deficit, int(max_wheat_budget // 25))
                else:
                    buy_wheat = 0
            elif p22a_enabled and day >= 29:
                buy_wheat = 0
            else:
                # While NE is pending, maintain a safe 5-day survival buffer rather than 20-day expansion
                wheat_buffer_target = 5 if (day <= 5 or (next_quadrant == 2 and day <= 8)) and (n_animals > 0 or buy_animal) else FEED_WHEAT_BUFFER_DAYS
                try:
                    from config import BOOTSTRAP_LIVESTOCK_ARM
                except Exception:
                    BOOTSTRAP_LIVESTOCK_ARM = "none"
                eff_buy_count = min(2, sum(buy_animal.values())) if (day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None)) else sum(buy_animal.values())
                wheat_needed = (n_animals + eff_buy_count) * wheat_buffer_target
                if trigger:
                    wheat_needed = max(wheat_needed, deficit)

                if wheat_have < wheat_needed:
                    # Protect $1,000 NE land capital from non-survival feed buffering on Days 5-6
                    ne_protect = 1000.0 if (next_quadrant == 2 and 5 <= day <= 6 and not buy_land) else 0.0
                    max_wheat_budget = max(0.0, available_before_seeds - ne_protect)
                    # Survival floor: always guarantee at least 2 days emergency feed
                    survival_floor = max(0, (n_animals * 2) - wheat_have) * 25.0
                    max_wheat_budget = max(max_wheat_budget, min(available_before_seeds, survival_floor))

                    buy_wheat = min(wheat_needed - wheat_have, int(max_wheat_budget // 25))
        wheat_feed_cost = buy_wheat * 25
        protected_feed_wheat = int(feed_shortfall_units)
        optional_feed_wheat = max(0, buy_wheat - protected_feed_wheat)
        if "feed_risk" in plan.diagnostics:
            plan.diagnostics["feed_risk"]["macro_buy_wheat_intent"] = int(buy_wheat)
            plan.diagnostics["feed_risk"]["feed_shortfall_units"] = int(feed_shortfall_units)
            plan.diagnostics["feed_risk"]["protected_feed_wheat"] = int(protected_feed_wheat)
            plan.diagnostics["feed_risk"]["optional_feed_wheat"] = int(optional_feed_wheat)

        # Discretionary budget: protect land capital if protection active, without double-counting reserve
        discretionary_budget = max(0.0, available_before_seeds - animal_cost)
        if land_capital_protection_active and not buy_land and next_quadrant is not None:
            targets = expansion_seed_targets(next_quadrant, day, money)
            seed_tranche = sum(CROPS[c]["seed"] * n for c, n in targets.items())
            n_extra = len(farm.unlocked) - 1
            target_land_price = LAND_PRICES[n_extra] if n_extra < len(LAND_PRICES) else 0
            protected_land_capital = target_land_price + seed_tranche + feed_shortfall_cost
            discretionary_budget = max(0.0, available_before_seeds - protected_land_capital - animal_cost)

        seed_budget = max(0.0, discretionary_budget - wheat_feed_cost)
        remaining_money = seed_budget

        seeds = dict(private.seeds)
        if not is_endgame:

            # ---- v5.12: Leader-Calibrated Day-0 Melon Springboard ----
            # 12 Melons ($960), 8 Wheat ($80), 4 fallow NW tiles (5 including shed (4,4)).
            # Sells 72 melons on Day 10 for ~$15k-$18k cash surge; 48 wheat on Day 4 for NE fund.
            wheat_available = seeds.get("WHEAT", 0)
            planned = {}
            committed_counts = get_committed_crop_counts(farm)
            if day == 0:
                try:
                    from config import BOOTSTRAP_LIVESTOCK_ARM
                except Exception:
                    BOOTSTRAP_LIVESTOCK_ARM = "none"

                if BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None):
                    MIN_CROP_FLOOR_MELON = 4
                    MIN_CROP_FLOOR_WHEAT = 4
                    MIN_CROP_FLOOR_COST = 360.0
                    admitted_cows = buy_animal.get("COW", 0)
                    admitted_sheep = buy_animal.get("SHEEP", 0)
                    admitted_animal_cost = admitted_cows * 400.0 + admitted_sheep * 500.0
                    feed_wheat_cost = (admitted_cows + admitted_sheep) * 4 * 28.0
                    avail_crop_cash = max(0.0, float(farm.money) - 7.0 - self.reserve - admitted_animal_cost - feed_wheat_cost)
                    extra_crop_cash = max(0.0, avail_crop_cash - MIN_CROP_FLOOR_COST)
                    extra_melons = min(8, int(extra_crop_cash // 80.0))
                    extra_wheat = min(4, int((extra_crop_cash - extra_melons * 80.0) // 10.0))
                    melon_tiles = MIN_CROP_FLOOR_MELON + extra_melons
                    wheat_tiles = MIN_CROP_FLOOR_WHEAT + extra_wheat
                else:
                    melon_tiles = 12
                    wheat_tiles = 8

                # Idempotent Day-0: subtract crops already planted and owned seeds
                planted_melon = committed_counts.get("MELON", 0)
                planted_wheat = committed_counts.get("WHEAT", 0)
                have_melon = private.seeds.get("MELON", 0) if (private and hasattr(private, "seeds")) else 0
                have_wheat = private.seeds.get("WHEAT", 0) if (private and hasattr(private, "seeds")) else 0

                remaining_melon = max(0, melon_tiles - planted_melon)
                remaining_wheat = max(0, wheat_tiles - planted_wheat)

                available_empty_tiles = len(empty_tiles)
                plant_melon_count = min(remaining_melon, available_empty_tiles)
                avail_for_wheat = max(0, available_empty_tiles - plant_melon_count)
                plant_wheat_count = min(remaining_wheat, avail_for_wheat)

                for _ in range(plant_melon_count):
                    if empty_tiles:
                        pos = empty_tiles.pop(0)
                        plant_queue.append((pos, "MELON"))
                        seeds["MELON"] = max(0, seeds.get("MELON", 0) - 1)
                        planned["MELON"] = planned.get("MELON", 0) + 1
                        committed_counts["MELON"] = committed_counts.get("MELON", 0) + 1

                for _ in range(plant_wheat_count):
                    if empty_tiles:
                        pos = empty_tiles.pop(0)
                        plant_queue.append((pos, "WHEAT"))
                        seeds["WHEAT"] = max(0, seeds.get("WHEAT", 0) - 1)
                        planned["WHEAT"] = planned.get("WHEAT", 0) + 1
                        committed_counts["WHEAT"] = committed_counts.get("WHEAT", 0) + 1

                if hour < 17:
                    if plant_melon_count > have_melon:
                        buy_seed["MELON"] = plant_melon_count - have_melon
                    if plant_wheat_count > have_wheat:
                        buy_seed["WHEAT"] = plant_wheat_count - have_wheat

                seed_spend = (buy_seed.get("MELON", 0) * CROPS["MELON"]["seed"] +
                              buy_seed.get("WHEAT", 0) * CROPS["WHEAT"]["seed"])
                remaining_money = max(0.0, remaining_money - seed_spend)

                # Keep remaining NW tiles fallow (reserved for Strawberry wave / no cash leak)
                empty_tiles.clear()
            elif day < 3 and len(farm.unlocked) == 1:
                # Days 1-2: plant any already-owned seeds (e.g. unplanted wheat from Day 0) into empty tiles,
                # but do NOT buy new seeds, and keep remaining tiles fallow for NE expansion.
                for crop in ("WHEAT", "MELON"):
                    while seeds.get(crop, 0) > 0 and empty_tiles:
                        pos = empty_tiles.pop(0)
                        seeds[crop] -= 1
                        plant_queue.append((pos, crop))
                        planned[crop] = planned.get(crop, 0) + 1
                        committed_counts[crop] = committed_counts.get(crop, 0) + 1
                empty_tiles.clear()
            else:
                # ---- SW Quadrant Dedicated Soil Planting Engine ----
                p41_sw_handled = False
                if "SW" in farm.unlocked:
                    try:
                        from config import (
                            get_p41_sw_zonal_expansion_enabled,
                            P41_SW_ZONE_COORDS,
                            get_p41_sw_crop_mode,
                        )
                        p41_sw_active = bool(get_p41_sw_zonal_expansion_enabled())
                    except Exception:
                        p41_sw_active = False

                    if p41_sw_active:
                        p41_sw_handled = True
                        empty_tiles = [p for p in empty_tiles if farm.quadrant_of(p) != "SW"]
                        sw_crop_mode = get_p41_sw_crop_mode() if "get_p41_sw_crop_mode" in locals() else "hybrid"

                        p41_planted_this_turn = []
                        p41_bought_this_turn = {}

                        for pos in P41_SW_ZONE_COORDS:
                            t = farm.tile_at(pos) if hasattr(farm, "tile_at") else None
                            is_empty = False
                            if t is not None:
                                is_empty = (
                                    not getattr(t, "is_plant", False)
                                    and not getattr(t, "is_animal", False)
                                    and getattr(t, "kind", "EMPTY") == "EMPTY"
                                )
                            elif hasattr(farm, "iter_tiles"):
                                is_empty = any(
                                    tile.pos == pos and tile.kind == "EMPTY"
                                    for tile in farm.iter_tiles()
                                )

                            if not is_empty:
                                continue

                            chosen_crop = None
                            if sw_crop_mode == "wheat":
                                if day <= 26:
                                    chosen_crop = "WHEAT"
                            elif sw_crop_mode == "strawberry":
                                if day <= 16:
                                    chosen_crop = "STRAWBERRY"
                                elif day <= 26:
                                    chosen_crop = "WHEAT"
                            else:  # hybrid
                                if pos in P41_SW_ZONE_COORDS[:4]:
                                    if day <= 16:
                                        chosen_crop = "STRAWBERRY"
                                    elif day <= 26:
                                        chosen_crop = "WHEAT"
                                else:
                                    if day <= 26:
                                        chosen_crop = "WHEAT"
                                    elif day <= 27:
                                        chosen_crop = "CARROT"

                            if chosen_crop is not None:
                                seed_cost = CROPS[chosen_crop]["seed"]
                                if seeds.get(chosen_crop, 0) > 0:
                                    seeds[chosen_crop] -= 1
                                    plant_queue.append((pos, chosen_crop))
                                    planned[chosen_crop] = planned.get(chosen_crop, 0) + 1
                                    committed_counts[chosen_crop] = committed_counts.get(chosen_crop, 0) + 1
                                    p41_planted_this_turn.append((pos, chosen_crop))
                                    if chosen_crop == "WHEAT":
                                        wheat_have += 4
                                elif remaining_money >= seed_cost:
                                    buy_seed[chosen_crop] = buy_seed.get(chosen_crop, 0) + 1
                                    p41_bought_this_turn[chosen_crop] = p41_bought_this_turn.get(chosen_crop, 0) + 1
                                    remaining_money -= seed_cost

                        plan.diagnostics["p41_sw_crop_controller"] = {
                            "active": True,
                            "mode": sw_crop_mode,
                            "planted": p41_planted_this_turn,
                            "bought_seeds": p41_bought_this_turn,
                            "zone_coords": list(P41_SW_ZONE_COORDS),
                        }

                # Whitelist: strictly WHEAT (D9-24) or CARROT (D25-27), 0 strawberries/melons/tomatoes
                if "SW" in farm.unlocked and not p41_sw_handled:
                    try:
                        from config import SW_ACTIVATION_MODE
                    except Exception:
                        SW_ACTIVATION_MODE = "production"

                    if SW_ACTIVATION_MODE == "progressive":
                        from strategy.land_serviceability_model import compute_progressive_sw_activation

                        # Authoritative crop evaluation closure (Single Source of Truth)
                        def crop_eval_cb(tile_pos, d):
                            chosen, ev = evaluate_dynamic_sw_crop_choice(
                                day=d,
                                wheat_have=wheat_have,
                                n_animals=n_animals,
                                forecast=self.fc,
                                boosts=boosts,
                                committed_counts=committed_counts,
                                opp_advice=opp_advice,
                                return_ev=True,
                            )
                            c_cost = CROPS[chosen]["seed"] if (chosen and chosen in CROPS) else 10.0
                            return chosen, ev, c_cost

                        worker_pos = {0: tuple(getattr(farm, "farmer", (4, 4)))}
                        if hasattr(farm, "hands"):
                            for i_h, h in enumerate(farm.hands):
                                worker_pos[i_h + 1] = tuple(h)

                        activated_sw_tiles, prog_diag = compute_progressive_sw_activation(
                            farm=farm,
                            day=day,
                            money=remaining_money,
                            worker_positions=worker_pos,
                            crop_eval_func=crop_eval_cb,
                            horizon_turns=48,
                            safety_margin_fraction=0.15,
                            hour=hour,
                            private=private,
                            seeds_owned=dict(seeds),
                        )
                        plan.diagnostics["sw_progressive_activation"] = prog_diag
                        plan.diagnostics["sw_tile_rejections"] = prog_diag.get("rejections", {})
                        plan.diagnostics["sw_tile_rejection_counts"] = prog_diag.get("rejection_counts", {})

                        # Remove all SW empty tiles from general empty_tiles pool
                        empty_tiles = [p for p in empty_tiles if farm.quadrant_of(p) != "SW"]

                        for pos in activated_sw_tiles:
                            chosen_crop = evaluate_dynamic_sw_crop_choice(
                                day=day,
                                wheat_have=wheat_have,
                                n_animals=n_animals,
                                forecast=self.fc,
                                boosts=boosts,
                                committed_counts=committed_counts,
                                opp_advice=opp_advice,
                            )
                            seed_cost = CROPS[chosen_crop]["seed"]
                            if seeds.get(chosen_crop, 0) > 0:
                                seeds[chosen_crop] -= 1
                                plant_queue.append((pos, chosen_crop))
                                planned[chosen_crop] = planned.get(chosen_crop, 0) + 1
                                committed_counts[chosen_crop] = committed_counts.get(chosen_crop, 0) + 1
                                if chosen_crop == "WHEAT":
                                    wheat_have += 4
                            elif remaining_money >= seed_cost:
                                # Incremental seed demand: buy seeds first, queue planting once seeds arrive
                                buy_seed[chosen_crop] = buy_seed.get(chosen_crop, 0) + 1
                                remaining_money -= seed_cost
                            else:
                                continue
                    else:
                        # Discrete or Production SW activation
                        sw_soil_empty = [p for p in empty_tiles if p in SW_SOIL_TILES]
                        try:
                            from config import SW_GENERIC_PLANTING_GATE_ENABLED
                            generic_sw_gate = bool(SW_GENERIC_PLANTING_GATE_ENABLED)
                        except ImportError:
                            generic_sw_gate = False

                        if generic_sw_gate:
                            # P1.3-A: the dedicated SW controller has exclusive
                            # authority to authorize NEW planting anywhere in SW.
                            # Reserve its soil candidates above, then exclude all
                            # SW positions from every subsequent generic planting
                            # loop (especially the continuous wheat replant loop).
                            # Do not change crop care or existing SW assets.
                            generic_sw_tiles = [
                                p for p in empty_tiles
                                if farm.quadrant_of(p) == "SW"
                            ]
                            empty_tiles = [
                                p for p in empty_tiles
                                if farm.quadrant_of(p) != "SW"
                            ]
                            plan.diagnostics["sw_generic_planting_gate"] = {
                                "enabled": True,
                                "excluded_sw_empty_tiles": len(generic_sw_tiles),
                                "excluded_sw_pasture_empty_tiles": sum(
                                    p in SW_PASTURE_TILES for p in generic_sw_tiles
                                ),
                                "authorized_sw_soil_candidates": len(sw_soil_empty),
                            }
                        else:
                            # Exact P1.2 behavior with P1.3-A disabled.
                            empty_tiles = [p for p in empty_tiles if p not in SW_SOIL_TILES]
                        if sw_soil_empty:
                            from strategy.land_serviceability_model import (
                                get_sorted_sw_soil_tiles,
                                evaluate_sw_serviceability,
                            )
                            sorted_order = get_sorted_sw_soil_tiles()
                            sw_soil_empty.sort(key=lambda p: sorted_order.index(p) if p in sorted_order else 999)

                            try:
                                from config import (
                                    DYNAMIC_SW_CROPS_ENABLED,
                                    SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED,
                                    SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED,
                                )
                                use_dyn_crops = DYNAMIC_SW_CROPS_ENABLED
                                use_serviceability_activation = bool(SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED)
                                responsive_scheduler_enabled = bool(SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED)
                            except Exception:
                                use_dyn_crops = False
                                use_serviceability_activation = False
                                responsive_scheduler_enabled = False

                            if use_serviceability_activation:
                                # P1.2: activation is allowed only against the same
                                # surplus-capacity concept used by the responsive
                                # scheduler.  Fail closed if the scheduler treatment
                                # is not also active so the evaluator cannot authorize
                                # work under assumptions the executor will not honor.
                                if responsive_scheduler_enabled:
                                    is_serviceable, best_k, activation_diag = evaluate_sw_serviceability(
                                        day,
                                        farm,
                                        money,
                                        self.fc,
                                        target_quadrant=3,
                                        hour=hour,
                                        reserve_desired_herd=False,
                                        responsive_scheduler_capacity=True,
                                        activation_context=True,
                                    )
                                    serviceable_k = int(activation_diag.get("best_k_serviceable", 0) or 0)
                                    existing_sw_plants = sum(
                                        1
                                        for t in farm.iter_tiles()
                                        if farm.quadrant_of(t.pos) == "SW"
                                        and getattr(t, "is_plant", False)
                                    )
                                    activation_slots = max(0, serviceable_k - existing_sw_plants)

                                    try:
                                        from config import get_p13_tight_soil_enabled
                                        use_tight_soil = bool(get_p13_tight_soil_enabled())
                                    except Exception:
                                        use_tight_soil = False

                                    if use_tight_soil:
                                        from strategy.land_serviceability_model import evaluate_tight_sw_soil_capacity
                                        tight_ok, tight_slots, tight_diag = evaluate_tight_sw_soil_capacity(
                                            farm=farm,
                                            day=day,
                                            money=remaining_money,
                                            hour=hour,
                                            private=private,
                                        )
                                        if not tight_ok:
                                            is_serviceable = False
                                            activation_slots = 0
                                        else:
                                            activation_slots = min(activation_slots, tight_slots)
                                        plan.diagnostics["p13_tight_soil_gate"] = {
                                            "enabled": True,
                                            "tight_serviceable": bool(tight_ok),
                                            "tight_slots": int(tight_slots),
                                            "activation_slots": int(activation_slots),
                                            "reason": tight_diag.get("reason"),
                                            "surplus_capacity": tight_diag.get("surplus_capacity"),
                                            "rejection_counts": dict(tight_diag.get("rejection_counts", {})),
                                        }

                                    if not is_serviceable or activation_slots <= 0:
                                        active_sw_soil = []
                                    else:
                                        active_sw_soil = sw_soil_empty[:activation_slots]
                                    plan.diagnostics["sw_serviceability_activation"] = {
                                        **dict(activation_diag),
                                        "enabled": True,
                                        "is_serviceable": bool(is_serviceable),
                                        "nominal_best_k": int(best_k),
                                        "serviceable_k": serviceable_k,
                                        "existing_sw_plants": int(existing_sw_plants),
                                        "activation_slots": int(activation_slots),
                                        "activated_empty_tiles": len(active_sw_soil),
                                    }
                                else:
                                    is_serviceable = False
                                    best_k = 0
                                    active_sw_soil = []
                                    plan.diagnostics["sw_serviceability_activation"] = {
                                        "enabled": True,
                                        "is_serviceable": False,
                                        "reason": "responsive_scheduler_required",
                                        "nominal_best_k": 0,
                                        "serviceable_k": 0,
                                        "existing_sw_plants": 0,
                                        "activation_slots": 0,
                                        "activated_empty_tiles": 0,
                                    }
                            else:
                                # Preserve exact Control/P1/P1.1 activation behavior.
                                _, best_k, _ = evaluate_sw_serviceability(
                                    day, farm, money, self.fc, target_quadrant=3
                                )
                                active_sw_soil = sw_soil_empty[:best_k]

                            if not use_dyn_crops:
                                # Baseline exact 588b3f1 behavior
                                sw_dec = sw_plant_decision(day, len(active_sw_soil), wheat_have, n_animals, max_tiles=best_k)
                                sw_wheat = sw_dec.get("WHEAT", 0)
                                sw_carrot = sw_dec.get("CARROT", 0)

                                # Plant SW wheat
                                for pos in active_sw_soil[:sw_wheat]:
                                    seed_cost = CROPS["WHEAT"]["seed"]
                                    if seeds.get("WHEAT", 0) > 0:
                                        seeds["WHEAT"] -= 1
                                    elif remaining_money >= seed_cost:
                                        buy_seed["WHEAT"] = buy_seed.get("WHEAT", 0) + 1
                                        remaining_money -= seed_cost
                                    else:
                                        continue
                                    plant_queue.append((pos, "WHEAT"))
                                    planned["WHEAT"] = planned.get("WHEAT", 0) + 1
                                    committed_counts["WHEAT"] = committed_counts.get("WHEAT", 0) + 1

                                # Plant SW carrot (Carrot Blitz)
                                for pos in active_sw_soil[sw_wheat:sw_wheat + sw_carrot]:
                                    seed_cost = CROPS["CARROT"]["seed"]
                                    if seeds.get("CARROT", 0) > 0:
                                        seeds["CARROT"] -= 1
                                    elif remaining_money >= seed_cost:
                                        buy_seed["CARROT"] = buy_seed.get("CARROT", 0) + 1
                                        remaining_money -= seed_cost
                                    else:
                                        continue
                                    plant_queue.append((pos, "CARROT"))
                                    planned["CARROT"] = planned.get("CARROT", 0) + 1
                                    committed_counts["CARROT"] = committed_counts.get("CARROT", 0) + 1
                            else:
                                # Dynamic Authoritative SW Crop Evaluator
                                for pos in active_sw_soil:
                                    chosen_crop = evaluate_dynamic_sw_crop_choice(
                                        day=day,
                                        wheat_have=wheat_have,
                                        n_animals=n_animals,
                                        forecast=self.fc,
                                        boosts=boosts,
                                        committed_counts=committed_counts,
                                        opp_advice=opp_advice,
                                    )
                                    seed_cost = CROPS[chosen_crop]["seed"]
                                    if seeds.get(chosen_crop, 0) > 0:
                                        seeds[chosen_crop] -= 1
                                    elif remaining_money >= seed_cost:
                                        buy_seed[chosen_crop] = buy_seed.get(chosen_crop, 0) + 1
                                        remaining_money -= seed_cost
                                    else:
                                        continue
                                    plant_queue.append((pos, chosen_crop))
                                    planned[chosen_crop] = planned.get(chosen_crop, 0) + 1
                                    committed_counts[chosen_crop] = committed_counts.get(chosen_crop, 0) + 1
                                    if chosen_crop == "WHEAT":
                                        wheat_have += 4
                # ---- P2.0: Dynamic Second Melon Tranche (Days 10-12) ----
                try:
                    from config import get_p20_second_melon_tranche_enabled
                    p20_enabled = bool(get_p20_second_melon_tranche_enabled())
                except Exception:
                    p20_enabled = False

                if p20_enabled:
                    try:
                        from strategy.second_melon_evaluator import evaluate_second_melon_tranche
                    except ImportError:
                        from second_melon_evaluator import evaluate_second_melon_tranche

                    market_obs = ctx.get("market") if isinstance(ctx, dict) else getattr(ctx, "market", None)
                    best_melon_k, melon_diag = evaluate_second_melon_tranche(
                        day=day,
                        hour=hour,
                        farm=farm,
                        private=private,
                        market=market_obs,
                        forecast=self.fc,
                        committed_counts=committed_counts,
                        empty_tiles=list(empty_tiles),
                        available_money=remaining_money,
                        hires_today=hires,
                        opp_advice=opp_advice,
                    )
                    plan.diagnostics["p20_second_melon"] = melon_diag

                    if best_melon_k > 0:
                        usable_empty_core = [
                            p for p in empty_tiles
                            if farm.quadrant_of(p) in ("NW", "NE")
                            and p not in ((4, 4), (4, 5))
                        ]
                        melon_positions = usable_empty_core[:best_melon_k]
                        for pos in melon_positions:
                            seed_cost = CROPS["MELON"]["seed"]
                            if seeds.get("MELON", 0) > 0:
                                seeds["MELON"] -= 1
                            elif remaining_money >= seed_cost:
                                buy_seed["MELON"] = buy_seed.get("MELON", 0) + 1
                                remaining_money = max(0.0, remaining_money - seed_cost)
                            else:
                                break
                            empty_tiles.remove(pos)
                            plant_queue.append((pos, "MELON"))
                            planned["MELON"] = planned.get("MELON", 0) + 1
                            committed_counts["MELON"] = committed_counts.get("MELON", 0) + 1

                existing_wheat = committed_counts.get("WHEAT", 0)
                # Continuous wheat replanting engine (Leader-Calibrated: 8/20/30 active wheat tiles)
                # Days 6-9: Retain wheat target at 8 even if NE is unlocked
                # Days 10-13: Retain wheat target at 20 even if SW is unlocked (n_quads=3), preserving tiles for Strawberry and Melon waves
                n_quads = len(farm.unlocked)
                try:
                    from config import STRATEGIC_SW_OWNERSHIP_ENABLED
                    strategic_sw = STRATEGIC_SW_OWNERSHIP_ENABLED
                except Exception:
                    strategic_sw = False

                if strategic_sw:
                    quadrant_wheat_target = 8 if (n_quads == 1 or day <= 9) else 20
                else:
                    quadrant_wheat_target = (
                        8 if (n_quads == 1 or day <= 9)
                        else (20 if (n_quads == 2 or day <= 13) else 30)
                    )
                try:
                    from config import get_p23_marginal_wheat_allocation_enabled
                    p23_enabled = bool(get_p23_marginal_wheat_allocation_enabled())
                except Exception:
                    p23_enabled = False

                if p23_enabled:
                    # P2.3: Strict Terminal Maturation Guard
                    # Wheat requires 4 full days to reach maturity (plant_day + 4).
                    # Plantings on Day 26+ mature on Day 30+ (post-season) and produce 0 harvestable yield.
                    if day > 25:
                        wheat_cap = 0
                        wheat_needed = 0
                        wheat_to_plant = 0
                        plan.diagnostics["p23_marginal_wheat"] = {
                            "day": day,
                            "reason": "terminal_deadline_past",
                            "wheat_to_plant": 0,
                        }
                    else:
                        wheat_cap = min(len(empty_tiles) + existing_wheat, quadrant_wheat_target)
                        wheat_needed = max(0, wheat_cap - existing_wheat)
                        wheat_to_plant = min(wheat_needed, len(empty_tiles))
                        plan.diagnostics["p23_marginal_wheat"] = {
                            "day": day,
                            "reason": "normal_replant_maintained",
                            "wheat_to_plant": wheat_to_plant,
                        }
                else:
                    wheat_cap = min(len(empty_tiles) + existing_wheat, quadrant_wheat_target)
                    wheat_needed = max(0, wheat_cap - existing_wheat)
                    wheat_to_plant = min(wheat_needed, len(empty_tiles))
                wheat_available = seeds.get("WHEAT", 0)
                if wheat_to_plant > wheat_available:
                    needed_seeds = wheat_to_plant - wheat_available
                    if remaining_money >= needed_seeds * CROPS["WHEAT"]["seed"]:
                        buy_seed["WHEAT"] = buy_seed.get("WHEAT", 0) + needed_seeds
                        remaining_money = max(0.0, remaining_money - needed_seeds * CROPS["WHEAT"]["seed"])
                        wheat_available += needed_seeds
                    else:
                        affordable = int(remaining_money // CROPS["WHEAT"]["seed"])
                        needed_seeds = min(needed_seeds, affordable)
                        if needed_seeds > 0:
                            buy_seed["WHEAT"] = buy_seed.get("WHEAT", 0) + needed_seeds
                            remaining_money = max(0.0, remaining_money - needed_seeds * CROPS["WHEAT"]["seed"])
                            wheat_available += needed_seeds
                wheat_to_plant = min(wheat_available, wheat_to_plant, len(empty_tiles))

                for _ in range(wheat_to_plant):
                    if empty_tiles:
                        pos = empty_tiles.pop(0)
                        plant_queue.append((pos, "WHEAT"))
                        seeds["WHEAT"] = max(0, seeds.get("WHEAT", 0) - 1)
                        planned["WHEAT"] = planned.get("WHEAT", 0) + 1
                        committed_counts["WHEAT"] = committed_counts.get("WHEAT", 0) + 1

            # Dedicated Strawberry Wave (Fable Leader Heuristic):
            # Cap progression: 16 (Days 0-8) -> 18 (Days 9-12) -> 20 (Day 13) -> 0 (Day 14+)
            # Placement: NE first, then NW fallow tiles. NEVER in SW!
            try:
                from config import get_p21_dynamic_strawberry_allocation_enabled
                p21_straw_enabled = bool(get_p21_dynamic_strawberry_allocation_enabled())
            except Exception:
                p21_straw_enabled = False

            if p21_straw_enabled:
                try:
                    from strategy.strawberry_portfolio_evaluator import compute_dynamic_strawberry_cap
                except ImportError:
                    from strawberry_portfolio_evaluator import compute_dynamic_strawberry_cap

                shed_straw = private.shed.get("STRAWBERRY", 0) if hasattr(private, "shed") else 0
                shed_w = private.shed.get("WHEAT", 0) if hasattr(private, "shed") else 0
                s_cap, p21_straw_diag = compute_dynamic_strawberry_cap(
                    day=day,
                    farm_unlocked=farm.unlocked,
                    cur_market_inv=market_inv,
                    committed_strawberries=committed_counts.get("STRAWBERRY", 0),
                    shed_strawberry=shed_straw,
                    shed_wheat=shed_w,
                    remaining_money=remaining_money,
                )
                plan.diagnostics["p21_strawberry"] = p21_straw_diag
            else:
                s_cap = get_strawberry_cap(day, True)

            if 3 <= day <= STRAWBERRY_PLANT_DEADLINE and "NE" in farm.unlocked:
                current_strawberries = committed_counts.get("STRAWBERRY", 0)
                want_s = max(0, s_cap - current_strawberries)
                if want_s > 0:
                    ne_empty = [p for p in empty_tiles if farm.quadrant_of(p) == "NE"]
                    nw_empty = [p for p in empty_tiles if farm.quadrant_of(p) == "NW" and p not in ((4, 4), (4, 5))]
                    s_tiles = (ne_empty + nw_empty)[:want_s]
                    for pos in s_tiles:
                        seed_cost = CROPS["STRAWBERRY"]["seed"]
                        if seeds.get("STRAWBERRY", 0) > 0:
                            seeds["STRAWBERRY"] -= 1
                        elif remaining_money >= seed_cost:
                            buy_seed["STRAWBERRY"] = buy_seed.get("STRAWBERRY", 0) + 1
                            remaining_money -= seed_cost
                        else:
                            break
                        empty_tiles.remove(pos)
                        plant_queue.append((pos, "STRAWBERRY"))
                        planned["STRAWBERRY"] = planned.get("STRAWBERRY", 0) + 1
                        committed_counts["STRAWBERRY"] = committed_counts.get("STRAWBERRY", 0) + 1

            # v5.10: Expansion priority layer — bias scoring for deadline-critical crops
            # on expansion tiles. This injects into the existing Phase 2b loop,
            # not a separate planting system.
            exp_priorities = {}
            if next_quadrant is not None and next_quadrant in QUADRANT_UNLOCK_DAYS:
                exp_priorities = expansion_crop_priorities(next_quadrant, day)

            # Phase 2b: Fill remaining empty tiles with best-scoring crops
            for pos in list(empty_tiles):
                if farm.quadrant_of(pos) == "SW":
                    continue  # Hard barrier: SW never gets general/strawberry crops
                best_score, best_crop = -1e9, None
                quadrant = farm.quadrant_of(pos)

                # v5.10: Expansion tranche — priority bias for new quadrant tiles
                if exp_priorities and next_quadrant == 2 and quadrant == "NE" and pos in empty_tiles:
                    for forced_crop, bias in exp_priorities.items():
                        if not _crop_allowed_today(forced_crop, day):
                            continue
                        can_afford = (seeds.get(forced_crop, 0) > 0) or (remaining_money >= CROPS[forced_crop]["seed"])
                        if not can_afford:
                            continue
                        # v5.11: Use dynamic strawberry cap
                        if forced_crop == "STRAWBERRY":
                            cap = s_cap if p21_straw_enabled else get_strawberry_cap(day, "NE" in farm.unlocked)
                        else:
                            cap = CROP_TILE_CAPS.get(forced_crop, 99)
                        if committed_counts.get(forced_crop, 0) >= cap:
                            continue
                        own_for_this = committed_counts.get(forced_crop, 0) + 1
                        base_score, _ = _crop_score(forced_crop, day, self.fc, boosts,
                                                    own_for_this, n_animals, n_animals,
                                                    opp_advice=opp_advice)
                        score = base_score + bias
                        if score > best_score:
                            best_score, best_crop = score, forced_crop

                # Fallback: standard crop scoring
                if best_crop is None:
                    for crop in CROPS:
                        if not _crop_allowed_today(crop, day):
                            continue
                        can_afford = (seeds.get(crop, 0) > 0) or (remaining_money >= CROPS[crop]["seed"])
                        if not can_afford:
                            continue
                        # v5.11: Use dynamic strawberry cap
                        if crop == "STRAWBERRY":
                            cap = s_cap if p21_straw_enabled else get_strawberry_cap(day, "NE" in farm.unlocked)
                        else:
                            cap = CROP_TILE_CAPS.get(crop, 99)
                        if committed_counts.get(crop, 0) >= cap:
                            continue
                        own_for_this = committed_counts.get(crop, 0) + 1
                        score, _ = _crop_score(crop, day, self.fc, boosts,
                                               own_for_this, n_animals, n_animals,
                                               opp_advice=opp_advice)
                        if score > best_score:
                            best_score, best_crop = score, crop

                if best_crop is None or best_score <= 0:
                    break
                seed_cost = CROPS[best_crop]["seed"]
                if seeds.get(best_crop, 0) > 0:
                    seeds[best_crop] -= 1
                elif remaining_money >= seed_cost:
                    buy_seed[best_crop] = buy_seed.get(best_crop, 0) + 1
                    remaining_money -= seed_cost
                else:
                    continue
                plant_queue.append((pos, best_crop))
                planned[best_crop] = planned.get(best_crop, 0) + 1
                committed_counts[best_crop] = committed_counts.get(best_crop, 0) + 1
                empty_tiles.remove(pos)
        else:
            remaining_money = ctx["farm"].money - self.reserve

        # ---- v5.10: Seed pre-purchase for next-day land unlock ----
        if not is_endgame and next_quadrant is not None:
            pre_buy = compute_pre_buy_seeds(next_quadrant, day, remaining_money)
            for crop, n in pre_buy.items():
                if n > 0:
                    buy_seed[crop] = buy_seed.get(crop, 0) + n
                    remaining_money -= n * CROPS[crop]["seed"]

        # ---------------- hiring (computed above) ----------------------
        load = estimate_daily_load(ctx) + len(plant_queue)
        units_now = 1 + len(farm.hands)
        water_budget_exceeded = load > (units_now + hires) * EFFECTIVE_ACTIONS_PER_UNIT

        # ---------------- place queue (pickup -> place two-step) -------
        place_queue = []
        inv_hold = {}
        for i, inv in enumerate(private.inventories):
            for item in inv:
                inv_hold.setdefault(item, []).append(i)
        
        all_empty_structures = {t.pos: t.kind for t in farm.iter_tiles()
                                if t.kind in ("COOP", "PASTURE") and not t.is_animal}
        try:
            from config import SW_CELL_HOUSING_ENABLED
        except Exception:
            SW_CELL_HOUSING_ENABLED = False

        for animal in ANIMAL_LIST:
            struct = ANIMALS[animal]["structure"]
            free = [pos for pos, k in all_empty_structures.items() if k == struct]
            if not free:
                continue

            # Point 5: If SW cell housing is active and animal is COW/SHEEP,
            # prefer physically built empty SW pasture so the SW cell is occupied
            if SW_CELL_HOUSING_ENABLED and animal in ("COW", "SHEEP"):
                sw_free = [p for p in free if farm.quadrant_of(p) == "SW"]
                other_free = [p for p in free if farm.quadrant_of(p) != "SW"]
                ordered_free = sorted(sw_free) + sorted(other_free)
            else:
                ordered_free = sorted(free)

            held = inv_hold.get(animal, [])
            if held:
                for target_pos in ordered_free[:len(held)]:
                    place_queue.append({"op": "PLACE", "target": target_pos,
                                        "args": [animal]})
                    if target_pos in all_empty_structures:
                        del all_empty_structures[target_pos]
            elif private.shed.get(animal, 0) > 0:
                grab_qty = min(int(private.shed.get(animal, 0)), len(ordered_free))
                for _ in range(grab_qty):
                    place_queue.append({"op": "PICKUP",
                                        "target": (4, 4), "args": [animal]})

        # P0 Guarantee: structure tiles and planting tiles must be strictly mutually exclusive!
        structure_tiles_set = set(plan.build_queue)
        plant_tiles_set = {pos for pos, _ in plan.plant_queue}
        assert not (structure_tiles_set & plant_tiles_set), \
            f"Structure tiles {structure_tiles_set} and plant tiles {plant_tiles_set} must be mutually exclusive!"

        plan.plant_queue = plant_queue
        plan.water_budget_exceeded = water_budget_exceeded
        plan.place_queue = place_queue
        # Phase C1: ordered provisional animal candidate sequence
        provisional_seq = list(herd_plan.buy_animal_sequence) if herd_plan is not None else []
        plan.buy_animal_sequence = provisional_seq
        try:
            from config import BOOTSTRAP_LIVESTOCK_ARM
        except Exception:
            BOOTSTRAP_LIVESTOCK_ARM = "none"
        if (point2_mode == "live" and (day >= C4_LIVESTOCK_CUTOFF_DAY or pre_ne_mode in ("ne_first", "ne_escrow"))) or (day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None)):
            buy_animal = {
                "COW": provisional_seq.count("COW"),
                "SHEEP": provisional_seq.count("SHEEP"),
                "GOOSE": provisional_seq.count("GOOSE"),
            }
        plan.intents = {
            "hire": hires,
            "buy_land": buy_land,
            "buy_seed": buy_seed,
            "buy_animal": buy_animal,
            "buy_animal_sequence": provisional_seq,
            "buy_wheat": int(buy_wheat),
            "protected_feed_wheat": int(protected_feed_wheat),
            "optional_feed_wheat": int(optional_feed_wheat),
            "pending_structures": {"PASTURE": len(reserved_structure_tiles)},
        }

        # SW diagnostics and metrics
        sw_is_unlocked = "SW" in farm.unlocked
        if get_sw_tile_breakdown is not None:
            sw_breakdown = get_sw_tile_breakdown(farm)
            sw_strawberry = sw_breakdown["crops_strawberry"]
            sw_other_crops = sw_breakdown["crops_other"]
            sw_active = sw_breakdown["active"]
            sw_empty = sw_breakdown["empty"] if sw_is_unlocked else None
            sw_utilization = sw_breakdown["utilization"] if sw_is_unlocked else None
        else:
            sw_tiles = [t for t in farm.iter_tiles() if farm.quadrant_of(t.pos) == "SW"] if hasattr(farm, "iter_tiles") else []
            sw_strawberry = sum(1 for t in sw_tiles if getattr(t, "crop", None) == "STRAWBERRY")
            sw_other_crops = sum(1 for t in sw_tiles if getattr(t, "is_plant", False) and getattr(t, "crop", None) != "STRAWBERRY")
            sw_animals = sum(1 for t in sw_tiles if getattr(t, "is_animal", False))
            sw_structures = sum(1 for t in sw_tiles if getattr(t, "kind", None) in ("PASTURE", "COOP") and not getattr(t, "is_animal", False))
            sw_active = sw_strawberry + sw_other_crops + sw_animals + sw_structures if sw_is_unlocked else 0
            sw_empty = sum(1 for t in sw_tiles if getattr(t, "kind", None) == "EMPTY") if sw_is_unlocked else None
            sw_utilization = round(sw_active / 25.0, 4) if sw_is_unlocked else None

        sw_planned_sw = sum(1 for pos, _ in plant_queue if farm.quadrant_of(pos) == "SW") if hasattr(farm, "quadrant_of") else 0
        projected_sw_util = min(1.0, (sw_active + sw_planned_sw) / 25.0) if sw_is_unlocked else None

        # Memory tracking for cumulative empty tile days
        mem = ctx.get("memory", {}) if isinstance(ctx, dict) else {}
        if sw_is_unlocked and sw_empty is not None:
            mem["sw_empty_tile_days"] = mem.get("sw_empty_tile_days", 0) + sw_empty
            sw_empty_tile_days = mem.get("sw_empty_tile_days", 0)
        else:
            sw_empty_tile_days = None

        sw_buy_wait = "BUY" if (buy_land and next_quadrant == 3) else ("ALREADY_OWNED" if sw_is_unlocked else "WAIT")
        sw_reason_text = sw_reason if next_quadrant == 3 else ("already_owned" if sw_is_unlocked else "locked")

        sw_decision_diag = {
            "day": day,
            "money": round(money, 2),
            "SW buy/wait": sw_buy_wait,
            "ROI": round(land_roi, 2) if next_quadrant == 3 else 0.0,
            "buy_today_value": round(land_roi_info.get("buy_today_value", 0.0), 1),
            "wait_1_day_value": round(land_roi_info.get("wait_1_day_value", 0.0), 1),
            "delay_value": round(land_roi_info.get("delay_value", 0.0), 1),
            "SW utilization": round(sw_utilization, 3) if sw_utilization is not None else None,
            "SW empty tiles": sw_empty,
            "SW empty tile-days": sw_empty_tile_days,
            "projected utilization": round(projected_sw_util, 3) if projected_sw_util is not None else None,
            "strawberry tiles": sw_strawberry,
            "other crop tiles": sw_other_crops,
            "reason": sw_reason_text,
        }

        plan.diagnostics.update({
            "day": day,
            "money": money,
            "sw_unlocked": sw_is_unlocked,
            "sw_target_unlock_day": QUADRANT_UNLOCK_DAYS.get(3, "N/A"),
            "sw_deadline": STRAWBERRY_PLANT_DEADLINE,
            "sw_urgency": sw_urgency,
            "sw_reason": sw_reason,
            "required_sw_treasury": sw_info.get("treasury_requirement", 0),
            "sw_empty_tiles": sw_empty,
            "sw_planned_tiles": sw_planned_sw,
            "sw_planned_crop_mix": {c: sum(1 for _, cc in plant_queue if cc == c)
                                    for c in set(cc for _, cc in plant_queue)} if plant_queue else {},
            "strawberry_allowed": _crop_allowed_today("STRAWBERRY", day),
            "land_purchase_decision": buy_land,
            "sw_decision": sw_decision_diag,
            # v5.11: ROI and opportunity-window diagnostics
            "land_roi": land_roi,
            "land_roi_info": land_roi_info,
            "opportunity_window_factor": ow_factor,
            "adjusted_roi": land_roi * ow_factor,
            "land_expected_profit": land_roi_info.get("expected_profit", 0),
            "land_cost": land_roi_info.get("land_price", 0),
            "land_best_mix": land_roi_info.get("best_mix", {}),
            "n_own_tiles": n_own_tiles,
            # v5.11: Dynamic caps and targets
            "dynamic_strawberry_cap": get_strawberry_cap(day, "NE" in farm.unlocked),
            "dynamic_sw_seed_targets": expansion_seed_targets(next_quadrant, day, money) if next_quadrant else {},
        })

        # Point 2 Phase A: Shadow Feed/Herd Feasibility Evaluator (Diagnostic only)
        point2_mode = get_point2_feed_mode() if callable(get_point2_feed_mode) else "off"
        if point2_mode != "off" and build_feed_resource_ledger is not None:
            try:
                strategic_hold = float(hire_cost) + (float(land_cost) if buy_land else 0.0)
                shadow_ledger = build_feed_resource_ledger(
                    ctx,
                    hard_cash_hold=float(self.reserve),
                    strategic_cash_hold=strategic_hold,
                    horizon_days=FEED_OPERATIONAL_HORIZON_DAYS,
                )
                existing_ok, existing_res = evaluate_existing_herd_feasibility(shadow_ledger)

                cow_res = evaluate_incremental_candidate(shadow_ledger, "COW")
                cow_ok = cow_res.feasible
                sheep_res = evaluate_incremental_candidate(shadow_ledger, "SHEEP")
                sheep_ok = sheep_res.feasible
                goose_res = evaluate_incremental_candidate(shadow_ledger, "GOOSE")
                goose_ok = goose_res.feasible

                # Short sequential feasibility test on a cloned ledger (COW then SHEEP)
                seq_ledger = shadow_ledger.clone()
                seq_cow_res = evaluate_incremental_candidate(seq_ledger, "COW")
                seq_cow_ok = seq_cow_res.feasible
                seq_sheep_ok = False
                seq_sheep_res = None
                if seq_cow_ok:
                    commit_candidate_reservation(seq_ledger, seq_cow_res)
                    seq_sheep_res = evaluate_incremental_candidate(seq_ledger, "SHEEP")
                    seq_sheep_ok = seq_sheep_res.feasible

                plan.diagnostics["point2_feed_shadow"] = {
                    "mode": point2_mode,
                    "existing_feasible": existing_ok,
                    "existing_reason": existing_res.blocking_reason,
                    "existing_confidence": existing_res.execution_confidence,
                    "candidate_feasibility": {
                        "COW": cow_res.to_dict() if cow_res else None,
                        "SHEEP": sheep_res.to_dict() if sheep_res else None,
                        "GOOSE": goose_res.to_dict() if goose_res else None,
                    },
                    "sequential_test": {
                        "cow_possible": seq_cow_ok,
                        "cow_then_sheep_possible": seq_sheep_ok,
                        "cow_result": seq_cow_res.to_dict() if seq_cow_res else None,
                        "sheep_result": seq_sheep_res.to_dict() if seq_sheep_res else None,
                    },
                    "ledger_summary": shadow_ledger.to_dict(),
                }
            except Exception as e:
                plan.diagnostics["point2_feed_shadow"] = {
                    "mode": point2_mode,
                    "error": str(e),
                }

        # Phase C1 diagnostics: provisional candidates and feed hold diagnostics
        if herd_plan is not None:
            plan.diagnostics["provisional_candidates"] = list(herd_plan.provisional_candidates)
            plan.diagnostics["buy_animal_sequence"] = list(herd_plan.buy_animal_sequence)
        else:
            plan.diagnostics["provisional_candidates"] = []
            plan.diagnostics["buy_animal_sequence"] = []

        if planning_feed_ledger is not None and hasattr(planning_feed_ledger, "get_feed_hold_diagnostics"):
            plan.diagnostics["feed_hold_diagnostics"] = planning_feed_ledger.get_feed_hold_diagnostics()
        else:
            plan.diagnostics["feed_hold_diagnostics"] = {
                "existing_feed_cash_hold": 0.0,
                "candidate_feed_cash_hold": 0.0,
                "remaining_existing_feed_hold": 0.0,
                "candidate_feed_holds_total": 0.0,
            }

        return plan


def _mean_over(forecast, product, days):
    vals = [forecast.expected_price(product, d) for d in days]
    return sum(vals) / len(vals) if vals else 0.0


def estimate_daily_load(ctx):
    """Travel-aware daily action-count load estimation.

    Incorporates:
      - Base service load (watering, feeding, caring, fertilizing, harvesting, planting)
      - Spatial dispersion across unlocked quadrants
      - Quadrant transitions and diagonal penalties
      - Shed transit overhead for pickups and drop-offs
      - SW quadrant distance burden (long-distance transit from (4,4))
    """
    farm = ctx.get("farm")
    if farm is None or not hasattr(farm, "iter_tiles"):
        return 0
    day = ctx.get("day", 0)
    private = ctx.get("private")

    base_load = 0
    active_quads = set()
    sw_tile_count = 0

    # 1. Base tile load + spatial distribution
    for t in farm.iter_tiles():
        q = farm.quadrant_of(t.pos)
        if q not in farm.unlocked:
            continue
        if t.is_plant:
            active_quads.add(q)
            if q == "SW":
                sw_tile_count += 1
            base_load += 1 if not getattr(t, "watered_today", False) else 0
            if getattr(t, "yield_units", 0) > 0:
                base_load += 1
        elif t.is_animal:
            active_quads.add(q)
            if q == "SW":
                sw_tile_count += 1
            base_load += 1 if not getattr(t, "fed_today", False) else 0
            if getattr(t, "fertilizer_available", False):
                base_load += 1
            if not getattr(t, "cared_today", False):
                base_load += 1
            info = ANIMALS.get(t.animal)
            if info and getattr(t, "placed_day", None) is not None:
                if (day + 1 - t.placed_day - info["first_yield_day"]) % info["interval"] == 0:
                    base_load += 1

    # Empty unlocked tiles ready for planting
    seed_units = sum(private.seeds.values()) if private and hasattr(private, "seeds") else 0
    empty_unlocked = sum(
        1 for t in farm.iter_tiles()
        if t.kind == "EMPTY" and farm.quadrant_of(t.pos) in farm.unlocked
    )
    plants_to_do = min(seed_units, empty_unlocked)
    base_load += plants_to_do

    # 2. Shed trips overhead (pickups of feed, fertilizer, or placing animals)
    shed_trips = 0
    if private and hasattr(private, "shed"):
        shed = private.shed
        shed_animals = sum(int(shed.get(a, 0)) for a in ANIMAL_LIST)
        shed_trips += shed_animals * 3
        if int(shed.get("WHEAT", 0)) > 0:
            shed_trips += 3
        if int(shed.get("FERTILIZER", 0)) > 0:
            shed_trips += 3

    # 3. Spatial dispersion & quadrant transitions
    dispersion_burden = 0
    if len(active_quads) > 1:
        dispersion_burden = (len(active_quads) - 1) * 4
        if "SW" in active_quads and "NE" in active_quads:
            dispersion_burden += 4

    # 4. SW distance burden: one-time quadrant setup + clustered intra-quadrant dispersion
    # Clustered tiles do not incur round-trip overhead per tile; dispersion within SW is sub-linear.
    sw_burden = (6 + min(8, sw_tile_count // 3)) if sw_tile_count > 0 else 0

    return base_load + shed_trips + dispersion_burden + sw_burden

