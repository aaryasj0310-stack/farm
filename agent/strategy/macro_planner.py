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
from typing import Optional, Dict, Any, List, Tuple, Set

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
    SW_SOIL_TILES,
    SW_ESCROW_AMOUNT,
    get_target_hands,
    QUADRANT_UNLOCK_DAYS,
    QUADRANT_MONEY_THRESHOLDS,
    QUADRANT_HARD_BLOCK,
    get_strawberry_cap,
    get_sw_seed_targets,
    C4_LIVESTOCK_CUTOFF_DAY,
)
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
        plant_day = current_day
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
        placed = getattr(t, "placed_day", None)
        if placed is None:
            placed = day
        harvest_day = placed + 4
        if harvest_day <= season_end:
            fert_day = getattr(t, "fertilized_until_day", None)
            is_fert = fert_day is not None and fert_day >= placed
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


def compute_unavoidable_feed_shortfall(farm, private, day, n_animals, feed_buffer):
    """Compute unavoidable survival feed shortfall for existing animals.

    Reuses authoritative feed projections and enforces strict temporal validity:
    - Immediately usable wheat: shed inventory + worker-held inventory.
    - Future wheat harvests from in-ground tiles: can only cover feeding on/after
      their arrival day. Future harvests cannot cover near-term hunger.
    Returns (wheat_on_hand, projected_wheat_req, shortfall_units, shortfall_cost).
    """
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
                placed = getattr(t, "placed_day", None) if not isinstance(t, dict) else t.get("placed_day")
                if placed is None:
                    placed = day
                h_day = placed + 4
                fert_day = getattr(t, "fertilized_until_day", None) if not isinstance(t, dict) else t.get("fertilized_until_day")
                is_fert = fert_day is not None and fert_day >= placed
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
    shortfall_cost = float(max_deficit * 25.0)
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
        wheat_tile_days = [t.placed_day for t in wheat_tiles]
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

        pasture_eval = evaluate_pasture_candidates(
            farm=farm,
            day=day,
            empty_tiles=list(empty_tiles),
            current_animals=counts,
            crop_opportunity_val=crop_opp_val,
            crop_name=best_crop_name,
            cutoff_day=C4_LIVESTOCK_CUTOFF_DAY,
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
        if next_q_temp == 3 and "SW" not in farm.unlocked and day <= LAND_BUY_LAST_DAY:
            if day in (8, 9) and ctx["farm"].money >= 2000:
                land_reserve = 2000
                seed_reserve = 150
            elif day >= 11:
                land_reserve = 2000
                seed_reserve = 150
        elif next_q_temp == 2 and "NE" not in farm.unlocked and 3 <= day <= LAND_BUY_LAST_DAY:
            if ctx["farm"].money >= 1000:
                land_reserve = 1000

        day_0_seed_reserve = 1040 if day == 0 else 0
        ne_fund_reserve = 600 if "NE" not in farm.unlocked and day < 3 else 0
        cash_for_animals = max(0.0, ctx["farm"].money - future_hire_cost - self.reserve - seed_reserve - land_reserve - day_0_seed_reserve - ne_fund_reserve)

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

        if is_endgame or not allow_livestock or day in (3, 4, 5):
            dynamic_targets = {"COW": counts.get("COW", 0),
                               "SHEEP": counts.get("SHEEP", 0),
                               "GOOSE": 0}
            requested_herd_size = sum(dynamic_targets.values())
            final_feed_capped_herd_size = min(requested_herd_size, sustainable)
        else:
            raw_targets = get_animal_targets(
                day=day,
                money=cash_for_animals,
                shed_wheat=wheat_have,
                current_animals=counts,
                max_pastures=max_pastures,
                max_sustainable=sustainable,
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

        # Purchase affordable animals if empty pasture exists or is being built
        # Prioritize Sheep ($200/wool, $100 fert) and Cow ($160/milk, $100 fert); Zero Geese unless empty coop pre-exists
        # Stage 8B C4: Cap animal purchases and pasture construction on or after C4_LIVESTOCK_CUTOFF_DAY
        needed_new_pastures = 0
        if not is_endgame and allow_livestock:
            # Queue PASTURE construction if needed to reach targets or house owned animals
            # Only pasture species (COW + SHEEP) count toward target_pastures
            target_pastures = max(
                dynamic_targets.get("COW", 0) + dynamic_targets.get("SHEEP", 0),
                counts.get("COW", 0) + counts.get("SHEEP", 0)
            )
            # Correction 1: existing_pastures already includes empty pastures.
            # Do NOT subtract existing_empty_pastures again.
            needed_new_pastures = max(0, target_pastures - existing_pastures)

            existing_structs = existing_pastures + len(reserved_structure_tiles)
            while existing_structs < target_pastures and len(reserved_structure_tiles) < 2 and positive_pasture_cands:
                cand_info = positive_pasture_cands.pop(0)
                cand_pos = cand_info["pos"]
                reserved_structure_tiles.append((cand_pos, "BUILD_PASTURE"))
                existing_structs += 1

            # Purchase affordable animals up to total available housing (existing + queued today)
            total_pastures = existing_pastures + len(reserved_structure_tiles)
            animals_owned_or_buying = sum(counts.values()) + sum(buy_animal.values())
            housing_available = max(0, total_pastures - animals_owned_or_buying)

            for animal in ("SHEEP", "COW", "GOOSE"):
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
                needed_wheat = total_animals_planned * min(FEED_WHEAT_BUFFER_DAYS, days_left)
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
            placed = getattr(t, "placed_day", None)
            if placed is not None:
                matures = placed + 2
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
                    farm, private, day, n_animals, feed_buffer
                )

                # v5.11: Compute dynamic land ROI
                land_roi, land_roi_info = compute_land_roi(
                    next_quadrant, day, money, farm, self.fc,
                    n_own_tiles=n_own_tiles, n_opp_tiles=n_opp_tiles)

                # v5.11: Compute opportunity-window factor
                ow_factor = opportunity_window_factor(next_quadrant, day)
                adjusted_roi = land_roi * ow_factor

                # Labor serviceability check
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
                protection_start_day = 5 if next_quadrant == 2 else (11 if next_quadrant == 3 else 999)
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
                    is_purchase_hour=(hour == 0),
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
            # While NE is pending, maintain a safe 5-day survival buffer rather than 20-day expansion
            wheat_buffer_target = 5 if (day <= 5 or (next_quadrant == 2 and day <= 8)) and (n_animals > 0 or buy_animal) else FEED_WHEAT_BUFFER_DAYS
            wheat_needed = (n_animals + sum(buy_animal.values())) * wheat_buffer_target
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
        if "feed_risk" in plan.diagnostics:
            plan.diagnostics["feed_risk"]["macro_buy_wheat_intent"] = int(buy_wheat)

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
                melon_tiles = 12
                wheat_tiles = 8

                for _ in range(melon_tiles):
                    if empty_tiles:
                        pos = empty_tiles.pop(0)
                        plant_queue.append((pos, "MELON"))
                        seeds["MELON"] = max(0, seeds.get("MELON", 0) - 1)
                        planned["MELON"] = planned.get("MELON", 0) + 1
                        committed_counts["MELON"] = committed_counts.get("MELON", 0) + 1

                for _ in range(wheat_tiles):
                    if empty_tiles:
                        pos = empty_tiles.pop(0)
                        plant_queue.append((pos, "WHEAT"))
                        seeds["WHEAT"] = max(0, seeds.get("WHEAT", 0) - 1)
                        planned["WHEAT"] = planned.get("WHEAT", 0) + 1
                        committed_counts["WHEAT"] = committed_counts.get("WHEAT", 0) + 1

                have_melon = private.seeds.get("MELON", 0)
                if melon_tiles > have_melon:
                    buy_seed["MELON"] = melon_tiles - have_melon
                have_wheat = private.seeds.get("WHEAT", 0)
                if wheat_tiles > have_wheat:
                    buy_seed["WHEAT"] = wheat_tiles - have_wheat

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
                # Whitelist: strictly WHEAT (D9-24) or CARROT (D25-27), 0 strawberries/melons/tomatoes
                if "SW" in farm.unlocked:
                    sw_soil_empty = [p for p in empty_tiles if p in SW_SOIL_TILES]
                    empty_tiles = [p for p in empty_tiles if p not in SW_SOIL_TILES]
                    if sw_soil_empty:
                        from strategy.land_serviceability_model import (
                            get_sorted_sw_soil_tiles,
                            evaluate_sw_serviceability,
                        )
                        sorted_order = get_sorted_sw_soil_tiles()
                        sw_soil_empty.sort(key=lambda p: sorted_order.index(p) if p in sorted_order else 999)

                        _, best_k, _ = evaluate_sw_serviceability(day, farm, money, self.fc, target_quadrant=3)
                        active_sw_soil = sw_soil_empty[:best_k]

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

                existing_wheat = committed_counts.get("WHEAT", 0)
                # Continuous wheat replanting engine (Leader-Calibrated: 8/20/30 active wheat tiles)
                # Days 6-9: Retain wheat target at 8 even if NE is unlocked
                # Days 10-13: Retain wheat target at 20 even if SW is unlocked (n_quads=3), preserving tiles for Strawberry and Melon waves
                n_quads = len(farm.unlocked)
                quadrant_wheat_target = (
                    8 if (n_quads == 1 or day <= 9)
                    else (20 if (n_quads == 2 or day <= 13) else 30)
                )
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
            # Cap progression: 16 (Days 3-5) -> 18 (Days 6-8) -> 20 (Days 9-13) -> 0 (Day 14+)
            # Placement: NE first, then NW fallow tiles. NEVER in SW!
            if 3 <= day <= STRAWBERRY_PLANT_DEADLINE and "NE" in farm.unlocked:
                s_cap = get_strawberry_cap(day, True)
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
                            cap = get_strawberry_cap(day, len(farm.unlocked) >= 2)
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
                            cap = get_strawberry_cap(day, len(farm.unlocked) >= 2)
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
        for animal in ANIMAL_LIST:
            struct = ANIMALS[animal]["structure"]
            free = [pos for pos, k in all_empty_structures.items() if k == struct]
            if not free:
                continue
            held = inv_hold.get(animal, [])
            if held:
                for target_pos in sorted(free)[:len(held)]:
                    place_queue.append({"op": "PLACE", "target": target_pos,
                                        "args": [animal]})
            elif private.shed.get(animal, 0) > 0:
                grab_qty = min(int(private.shed.get(animal, 0)), len(free))
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
        plan.intents = {
            "hire": hires,
            "buy_land": buy_land,
            "buy_seed": buy_seed,
            "buy_animal": buy_animal,
            "buy_wheat": int(buy_wheat),
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
            "dynamic_strawberry_cap": get_strawberry_cap(day, "SW" in farm.unlocked),
            "dynamic_sw_seed_targets": expansion_seed_targets(next_quadrant, day, money) if next_quadrant else {},
        })

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

