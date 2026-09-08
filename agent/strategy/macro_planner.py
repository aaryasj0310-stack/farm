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
from strategy.animal_planner import get_animal_targets
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


def sw_plant_decision(day: int, free_tiles: int, wheat_stock: int, herd_size: int) -> dict:
    """Computes exact wheat and carrot seed allocation for free SW soil tiles.

    Mathematical specification:
    - Day >= 28: Fallow / harvest-only (0 seeds).
    - Day <= 25 and wheat_stock < feed_need: Allocate needed wheat seeds (ceil div).
    - Remainder of free tiles go to CARROT.
    - Day 27 EV gate: 0.5 * 3.5 * 70 - 20 = +102.5 > 0, so carrots are planted.
    """
    if day >= 28:
        return {"WHEAT": 0, "CARROT": 0}
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

        # --- wheat capacity projection (dynamic animal cap) ---
        wheat_tiles = [t for t in farm.iter_tiles()
                       if t.is_plant and t.crop == "WHEAT"]
        wheat_tile_days = [t.placed_day for t in wheat_tiles]
        days_left = SEASON_DAYS - day
        wheat_cap = compute_wheat_capacity(wheat_tile_days, day)
        wheat_have = int(private.shed.get("WHEAT", 0))
        sustainable = compute_sustainable_animals(wheat_cap, days_left)
        if day <= 2:
            sustainable = max(sustainable, PHASE1_GEESE_DAY0_2)

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

        # Dynamic animal targets computation (Leader-Calibrated Astra heuristic)
        existing_pastures = sum(1 for t in farm.iter_tiles() if t.kind == "PASTURE")
        if "SW" in farm.unlocked:
            sw_pasture_cands = [t for t in empty_tiles if t in SW_PASTURE_TILES]
            early_pasture_cands = [t for t in empty_tiles if t in EARLY_PASTURE_TILES]
            pasture_cands = sw_pasture_cands + early_pasture_cands
            max_pastures = min(9, existing_pastures + len(pasture_cands))
        else:
            early_pasture_cands = [t for t in empty_tiles if t in EARLY_PASTURE_TILES]
            pasture_cands = early_pasture_cands
            max_pastures = min(len(EARLY_PASTURE_TILES), existing_pastures + len(early_pasture_cands))

        # Discretionary cash reservation: wages, base reserve, and upcoming land/seed escrow
        future_hire_cost = sum(hire_total_cost(get_target_hands(d))
                               for d in range(day, min(day + 3, 30)))
        seed_reserve = 150 if "SW" not in farm.unlocked and day in (8, 9) else 0
        land_reserve = 2000 if "SW" not in farm.unlocked and day in (8, 9) and ctx["farm"].money >= 2000 else (
            1000 if "NE" not in farm.unlocked and day in (3, 4) and ctx["farm"].money >= 1000 else 0
        )
        day_0_seed_reserve = 1040 if day == 0 else 0
        ne_fund_reserve = 600 if "NE" not in farm.unlocked and day < 3 else 0
        cash_for_animals = max(0.0, ctx["farm"].money - future_hire_cost - self.reserve - seed_reserve - land_reserve - day_0_seed_reserve - ne_fund_reserve)

        # Dynamic animal targets via corrected Astra heuristic
        # Stage 8B C4: Cease new livestock investment on or after C4_LIVESTOCK_CUTOFF_DAY (Day 12).
        # Days 3-5: Protect NE land fund ($1,000) and workforce ramp.
        if is_endgame or day >= C4_LIVESTOCK_CUTOFF_DAY or day in (3, 4, 5):
            dynamic_targets = {"COW": counts.get("COW", 0),
                               "SHEEP": counts.get("SHEEP", 0),
                               "GOOSE": 0}
        else:
            dynamic_targets = get_animal_targets(
                day=day,
                money=cash_for_animals,
                shed_wheat=wheat_have,
                current_animals=counts,
                max_pastures=max_pastures,
            )

        # Purchase affordable animals if empty pasture exists or is being built
        # Prioritize Sheep ($200/wool, $100 fert) and Cow ($160/milk, $100 fert); Zero Geese unless empty coop pre-exists
        # Stage 8B C4: Cap animal purchases and pasture construction on or after C4_LIVESTOCK_CUTOFF_DAY
        if not is_endgame and day < C4_LIVESTOCK_CUTOFF_DAY:
            # Queue PASTURE construction if needed to reach targets or house owned animals
            target_pastures = max(
                dynamic_targets.get("COW", 0) + dynamic_targets.get("SHEEP", 0),
                counts.get("COW", 0) + counts.get("SHEEP", 0)
            )
            existing_structs = existing_pastures + len(reserved_structure_tiles)
            while existing_structs < target_pastures and len(reserved_structure_tiles) < 2 and pasture_cands:
                cand = pasture_cands.pop(0)
                if cand in empty_tiles:
                    empty_tiles.remove(cand)
                reserved_structure_tiles.append((cand, "BUILD_PASTURE"))
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

        # structure build queue: use specific build_op
        if reserved_structure_tiles:
            plan.build_op = "BUILD_PASTURE"
            plan.build_queue = [t for t, _ in reserved_structure_tiles[:2]]

        # ---------------- crop queue on remaining tiles ----------------
        # Reserve remaining SW_PASTURE_TILES and EARLY_PASTURE_TILES for pasture construction only — never plant crops on them
        if "SW" in farm.unlocked:
            empty_tiles = [t for t in empty_tiles if t not in SW_PASTURE_TILES]
        elif day < 3:
            empty_tiles = [t for t in empty_tiles if t not in EARLY_PASTURE_TILES]

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

        if not is_endgame and next_quadrant is not None:
            if next_quadrant in QUADRANT_HARD_BLOCK:
                sw_reason = "hard_blocked"
            elif next_quadrant in QUADRANT_UNLOCK_DAYS:
                # Compute feed cost for treasury gate
                feed_buffer = 5 if day <= 5 and (n_animals > 0 or buy_animal) else FEED_WHEAT_BUFFER_DAYS
                feed_cost = (n_animals + sum(buy_animal.values())) * feed_buffer * 25

                # v5.11: Compute dynamic land ROI
                land_roi, land_roi_info = compute_land_roi(
                    next_quadrant, day, money, farm, self.fc,
                    n_own_tiles=n_own_tiles, n_opp_tiles=n_opp_tiles)

                # v5.11: Compute opportunity-window factor
                ow_factor = opportunity_window_factor(next_quadrant, day)

                # Use expansion planner's non-negotiable purchase gate
                # v5.11: Pass ow_factor to gate — adjusted_roi = roi * ow_factor
                buy_land, sw_reason, sw_info = should_buy_land(
                    next_quadrant, day, money, farm,
                    hire_cost=hire_cost, feed_cost=feed_cost,
                    animal_cost=sum(ANIMALS[a]["cost"] * k for a, k in buy_animal.items()),
                    reserve=self.reserve, roi=land_roi,
                    ow_factor=ow_factor,
                    forecast=self.fc,
                )
                if buy_land:
                    land_cost = LAND_PRICES[n_extra_unlocked]

                # Compute urgency for treasury hoarding (does NOT loosen gate)
                sw_urgency, _, sw_info = compute_land_urgency(
                    next_quadrant, day, money, farm)

        animal_cost = sum(ANIMALS[a]["cost"] * k for a, k in buy_animal.items())

        # Feed wheat buffer needed for existing + newly bought animals
        buy_wheat = 0
        effective_reserve = 50 if (day in (3, 4, 5, 6) and "NE" in farm.unlocked) else self.reserve
        post_hire_money = max(0.0, money - hire_cost)
        available_before_seeds = max(0.0, post_hire_money - effective_reserve - land_cost - animal_cost)

        if plan.feeding_enabled:
            wheat_buffer_target = 5 if day <= 5 and (n_animals > 0 or buy_animal) else FEED_WHEAT_BUFFER_DAYS
            wheat_needed = (n_animals + sum(buy_animal.values())) * wheat_buffer_target
            if trigger:
                wheat_needed = max(wheat_needed, deficit)

            if wheat_have < wheat_needed:
                buy_wheat = min(wheat_needed - wheat_have, int(available_before_seeds // 25))
        wheat_feed_cost = buy_wheat * 25

        available_before_seeds = max(0.0, post_hire_money - effective_reserve - land_cost - animal_cost)

        # v5.10: Protect SW treasury from discretionary spending
        # When expansion is urgent but not yet purchased, reserve the fund
        # Do NOT hoard SW land fund before Day 11 when melons are in the ground — melon harvest provides $18k!
        discretionary_budget = available_before_seeds
        if sw_urgency >= 0.5 and not buy_land and next_quadrant is not None and day >= 11:
            # v5.11: Use dynamic targets
            targets = expansion_seed_targets(next_quadrant, day, money)
            seed_reserve = sum(CROPS[c]["seed"] * n for c, n in targets.items())
            n_extra = len(farm.unlocked) - 1
            land_reserve = LAND_PRICES[n_extra] if n_extra < len(LAND_PRICES) else 0
            sw_treasury_need = land_reserve + seed_reserve + effective_reserve
            discretionary_budget = max(0.0, available_before_seeds - sw_treasury_need)

        seed_budget = max(0.0, discretionary_budget - wheat_feed_cost)
        remaining_money = seed_budget

        seeds = dict(private.seeds)
        if not is_endgame:

            # ---- v5.12: Leader-Calibrated Day-0 Melon Springboard ----
            # 12 Melons ($960), 8 Wheat ($80), 4 fallow NW tiles (5 including shed (4,4)).
            # Sells 72 melons on Day 10 for ~$15k-$18k cash surge; 48 wheat on Day 4 for NE fund.
            wheat_available = seeds.get("WHEAT", 0)
            planned = {}
            if day == 0:
                melon_tiles = 12
                wheat_tiles = 8

                for _ in range(melon_tiles):
                    if empty_tiles:
                        pos = empty_tiles.pop(0)
                        plant_queue.append((pos, "MELON"))
                        seeds["MELON"] = max(0, seeds.get("MELON", 0) - 1)
                        planned["MELON"] = planned.get("MELON", 0) + 1

                for _ in range(wheat_tiles):
                    if empty_tiles:
                        pos = empty_tiles.pop(0)
                        plant_queue.append((pos, "WHEAT"))
                        seeds["WHEAT"] = max(0, seeds.get("WHEAT", 0) - 1)
                        planned["WHEAT"] = planned.get("WHEAT", 0) + 1

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
                empty_tiles.clear()
            else:
                # ---- SW Quadrant Dedicated Soil Planting Engine ----
                # Whitelist: strictly WHEAT (D9-24) or CARROT (D25-27), 0 strawberries/melons/tomatoes
                if "SW" in farm.unlocked:
                    sw_soil_empty = [p for p in empty_tiles if p in SW_SOIL_TILES]
                    empty_tiles = [p for p in empty_tiles if p not in SW_SOIL_TILES]
                    if sw_soil_empty:
                        sw_dec = sw_plant_decision(day, len(sw_soil_empty), wheat_have, n_animals)
                        sw_wheat = sw_dec.get("WHEAT", 0)
                        sw_carrot = sw_dec.get("CARROT", 0)

                        # Plant SW wheat
                        for pos in sw_soil_empty[:sw_wheat]:
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

                        # Plant SW carrot (Carrot Blitz)
                        for pos in sw_soil_empty[sw_wheat:sw_wheat + sw_carrot]:
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

                existing_wheat = sum(1 for t in farm.iter_tiles() if t.is_plant and t.crop == "WHEAT") + planned.get("WHEAT", 0)
                # Continuous wheat replanting engine (Leader-Calibrated: 8/20/30 active wheat tiles)
                n_quads = len(farm.unlocked)
                quadrant_wheat_target = 8 if n_quads == 1 else (20 if n_quads == 2 else 30)
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

            # Dedicated Strawberry Wave (Fable Leader Heuristic):
            # Cap progression: 16 (Days 3-5) -> 18 (Days 6-8) -> 20 (Days 9-13) -> 0 (Day 14+)
            # Placement: NE first, then NW fallow tiles. NEVER in SW!
            if 3 <= day <= STRAWBERRY_PLANT_DEADLINE and "NE" in farm.unlocked:
                s_cap = get_strawberry_cap(day, True)
                current_strawberries = sum(1 for t in farm.iter_tiles() if getattr(t, "crop", None) == "STRAWBERRY") + planned.get("STRAWBERRY", 0)
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
                        if planned.get(forced_crop, 0) >= cap:
                            continue
                        own_for_this = planned.get(forced_crop, 0) + 1
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
                        if planned.get(crop, 0) >= cap:
                            continue
                        own_for_this = planned.get(crop, 0) + 1
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
        sw_tiles = [t for t in farm.iter_tiles() if farm.quadrant_of(t.pos) == "SW"] if hasattr(farm, "iter_tiles") else []
        sw_strawberry = sum(1 for t in sw_tiles if getattr(t, "crop", None) == "STRAWBERRY")
        sw_other_crops = sum(1 for t in sw_tiles if getattr(t, "is_plant", False) and getattr(t, "crop", None) != "STRAWBERRY")
        sw_animals = sum(1 for t in sw_tiles if getattr(t, "is_animal", False) or getattr(t, "kind", None) in ("COOP", "PASTURE"))
        sw_active = sw_strawberry + sw_other_crops + sw_animals
        sw_empty = max(0, 25 - sw_active) if sw_is_unlocked else 25
        sw_utilization = (sw_active / 25.0) if sw_is_unlocked else 0.0
        sw_planned_sw = sum(1 for pos, _ in plant_queue if farm.quadrant_of(pos) == "SW")
        projected_sw_util = min(1.0, (sw_active + sw_planned_sw) / 25.0) if sw_is_unlocked else 0.0

        # Memory tracking for cumulative empty tile days
        mem = ctx.get("memory", {}) if isinstance(ctx, dict) else {}
        if sw_is_unlocked:
            mem["sw_empty_tile_days"] = mem.get("sw_empty_tile_days", 0) + sw_empty
        sw_empty_tile_days = mem.get("sw_empty_tile_days", 0) if sw_is_unlocked else 0

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
            "SW utilization": round(sw_utilization, 3),
            "SW empty tiles": sw_empty,
            "SW empty tile-days": sw_empty_tile_days,
            "projected utilization": round(projected_sw_util, 3),
            "strawberry tiles": sw_strawberry,
            "other crop tiles": sw_other_crops,
            "reason": sw_reason_text,
        }

        plan.diagnostics = {
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
        }

        return plan


def _mean_over(forecast, product, days):
    vals = [forecast.expected_price(product, d) for d in days]
    return sum(vals) / len(vals) if vals else 0.0


def estimate_daily_load(ctx):
    """Rough action-count needed today."""
    farm = ctx["farm"]
    plants = sum(1 for t in farm.iter_tiles() if t.is_plant)
    animals = sum(1 for t in farm.iter_tiles() if t.is_animal)
    return plants * 2 + animals * 3
