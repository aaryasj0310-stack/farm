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
    get_target_hands,
    get_animal_targets,
    QUADRANT_UNLOCK_DAYS,
    QUADRANT_MONEY_THRESHOLDS,
    QUADRANT_HARD_BLOCK,
    get_strawberry_cap,
    get_sw_seed_targets,
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
    build_op: str = "BUILD_COOP"
    place_queue: list = field(default_factory=list)      # [{op,target,args}]
    intents: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)      # v5.10: expansion observability


def _crop_allowed_today(crop, day):
    """True if planted today it still completes its final harvest by day 29."""
    if day > 25:
        return False  # v5.9: STOP all seed purchases after day 25
    cd = CROPS[crop]
    if cd["ongoing"]:
        # latest scheduled production: first + (count-1) * interval
        last_harvest = cd["first_yield_day"] + (cd["max_yield"] - 1) * cd["interval"]
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
                       farm.quadrant_of(t.pos) in farm.unlocked]

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

        # Dynamic animal targets computation (Leader-Calibrated 5-constraint optimizer)
        n_unlocked = len(farm.unlocked)
        total_tiles = n_unlocked * 25
        min_crop_reserve = 12 if n_unlocked == 1 else (24 if n_unlocked == 2 else 32)
        space_cap = max(0, total_tiles - min_crop_reserve)

        # Feed capacity from current + projected wheat production
        wheat_have = int(private.shed.get("WHEAT", 0)) if private else 0
        wheat_growing = sum(project_wheat_harvests(t.placed_day, day) for t in farm.iter_tiles() if t.is_plant and t.crop == "WHEAT")
        days_left_season = max(1, 29 - day)
        projected_feed = (12 * (days_left_season // 4) * 6) if day <= 20 else 0
        feed_cap = max(4, (wheat_have + wheat_growing + projected_feed) // (days_left_season + 2))

        # Labor capacity from workforce actions
        total_daily_actions = (1 + target_hands) * 24
        plants_count = sum(1 for t in farm.iter_tiles() if t.is_plant)
        spare_actions = max(0, total_daily_actions - int(plants_count * 1.5) - 10)
        labor_cap = max(2, int(spare_actions // 3.0))

        # Hard max herd size
        max_herd = min(space_cap, feed_cap, labor_cap, 20)
        if day >= 22:
            max_herd = min(max_herd, n_animals)  # stop new animal expansion in late endgame

        # Dynamic species targets (Leader mix: Cows & Sheep high-value core, Geese auxiliary)
        if max_herd > 0:
            cows_target = int(round(max_herd * 0.45))
            sheep_target = int(round(max_herd * 0.45))
            geese_target = max(0, max_herd - cows_target - sheep_target)
            dynamic_targets = {"COW": cows_target, "SHEEP": sheep_target, "GOOSE": geese_target}
        else:
            dynamic_targets = {"COW": 0, "SHEEP": 0, "GOOSE": 0}

        # endgame: no new animals — just feed what we have
        if not is_endgame and day <= 21:
            future_hire_cost = sum(hire_total_cost(get_target_hands(d))
                                   for d in range(day, min(day + 3, 30)))
            cash_for_animals = max(0, ctx["farm"].money - future_hire_cost - self.reserve)
            
            for animal in ("COW", "SHEEP", "GOOSE"):
                target = dynamic_targets.get(animal, 0)
                info = ANIMALS[animal]
                struct_kind = info["structure"]
                free_struct = [pos for pos, k in structures_empty.items()
                               if k == struct_kind]
                
                # If an empty structure of this kind exists on board, fill it
                if free_struct and (counts.get(animal, 0) < target or n_animals + sum(buy_animal.values()) < max_herd):
                    if cash_for_animals >= info["cost"]:
                        buy_animal[animal] = buy_animal.get(animal, 0) + 1
                        cash_for_animals -= info["cost"]
                        del structures_empty[free_struct[0]]
                        continue

                deficit_a = target - counts.get(animal, 0)
                if deficit_a <= 0:
                    continue
                if cash_for_animals < info["cost"]:
                    continue

                if empty_tiles:
                    # Queue structure build on empty tile (up to 2 structures per day)
                    existing_structs = sum(1 for t in farm.iter_tiles() if t.kind == struct_kind) + len(reserved_structure_tiles)
                    target_structs = target if animal == "GOOSE" else (dynamic_targets.get("COW", 0) + dynamic_targets.get("SHEEP", 0))
                    if existing_structs < target_structs and len(reserved_structure_tiles) < 2 and len(empty_tiles) > 5:
                        tile = empty_tiles.pop(0)
                        reserved_structure_tiles.append((tile, "BUILD_" + struct_kind))

        # structure build queue: use specific build_op
        if reserved_structure_tiles:
            plan.build_op = reserved_structure_tiles[0][1]
            plan.build_queue = [t for t, _ in reserved_structure_tiles[:2]]

        # ---------------- crop queue on remaining tiles ----------------
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
        if plan.feeding_enabled:
            wheat_buffer_target = 5 if day <= 5 and (n_animals > 0 or buy_animal) else FEED_WHEAT_BUFFER_DAYS
            wheat_needed = (n_animals + sum(buy_animal.values())) * wheat_buffer_target
            if trigger:
                wheat_needed = max(wheat_needed, deficit)

            post_hire_money = max(0.0, money - hire_cost)
            available_before_seeds = max(0.0, post_hire_money - self.reserve - land_cost - animal_cost)
            if wheat_have < wheat_needed:
                buy_wheat = min(wheat_needed - wheat_have, int(available_before_seeds // 25))
        wheat_feed_cost = buy_wheat * 25

        post_hire_money = max(0.0, money - hire_cost)
        available_before_seeds = max(0.0, post_hire_money - self.reserve - land_cost - animal_cost)

        # v5.10: Protect SW treasury from discretionary spending
        # When expansion is urgent but not yet purchased, reserve the fund
        discretionary_budget = available_before_seeds
        if sw_urgency >= 0.5 and not buy_land and next_quadrant is not None:
            # v5.11: Use dynamic targets
            targets = expansion_seed_targets(next_quadrant, day, money)
            seed_reserve = sum(CROPS[c]["seed"] * n for c, n in targets.items())
            n_extra = len(farm.unlocked) - 1
            land_reserve = LAND_PRICES[n_extra] if n_extra < len(LAND_PRICES) else 0
            sw_treasury_need = land_reserve + seed_reserve + self.reserve
            discretionary_budget = max(0.0, available_before_seeds - sw_treasury_need)

        seed_budget = max(0.0, discretionary_budget - wheat_feed_cost)
        remaining_money = seed_budget

        seeds = dict(private.seeds)
        if not is_endgame:

            # ---- v5.10: Day-0 portfolio allocator ----
            # Balance wheat/feed vs high-value cash crops vs treasury for expansion
            wheat_available = seeds.get("WHEAT", 0)
            if day == 0:
                total_tiles = len(empty_tiles)

                # Minimum wheat: animal feed backbone + safety margin
                min_wheat = min(total_tiles, max(8, n_animals * 3))

                # Treasury deduction: reserve for SW expansion if approaching
                treasury_deduction = 0
                if sw_urgency >= 0.3 and next_quadrant is not None:
                    # v5.11: Use dynamic targets
                    targets = expansion_seed_targets(next_quadrant, day, money)
                    seed_reserve = sum(CROPS[c]["seed"] * n for c, n in targets.items())
                    n_extra = len(farm.unlocked) - 1
                    land_reserve = LAND_PRICES[n_extra] if n_extra < len(LAND_PRICES) else 0
                    treasury_deduction = min(remaining_money * 0.3, land_reserve + seed_reserve)

                available_for_seeds = max(0.0, remaining_money - treasury_deduction)

                # Phase 0a: Plant minimum wheat
                wheat_to_plant = min_wheat
                if wheat_to_plant > wheat_available:
                    needed_seeds = wheat_to_plant - wheat_available
                    wheat_seed_cost = needed_seeds * CROPS["WHEAT"]["seed"]
                    if available_for_seeds >= wheat_seed_cost:
                        buy_seed["WHEAT"] = buy_seed.get("WHEAT", 0) + needed_seeds
                        available_for_seeds -= wheat_seed_cost
                        seeds["WHEAT"] = wheat_to_plant
                    else:
                        affordable = int(available_for_seeds // CROPS["WHEAT"]["seed"])
                        wheat_to_plant = wheat_available + affordable
                        if affordable > 0:
                            buy_seed["WHEAT"] = buy_seed.get("WHEAT", 0) + affordable
                            available_for_seeds -= affordable * CROPS["WHEAT"]["seed"]
                        seeds["WHEAT"] = wheat_to_plant

                remaining_money = available_for_seeds
            else:
                existing_wheat = sum(1 for t in farm.iter_tiles() if t.is_plant and t.crop == "WHEAT")
                # Continuous wheat replanting engine (Leader-Calibrated: 8/20/30 active wheat tiles)
                n_quads = len(farm.unlocked)
                quadrant_wheat_target = 8 if n_quads == 1 else (20 if n_quads == 2 else 30)
                wheat_cap = min(len(empty_tiles) + existing_wheat, quadrant_wheat_target)
                wheat_needed = max(0, wheat_cap - existing_wheat)
                wheat_to_plant = min(wheat_needed, len(empty_tiles))
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

            # Track planned counts for portfolio-aware scoring
            planned = {"WHEAT": wheat_to_plant} if wheat_to_plant > 0 else {}

            # v5.10: Expansion priority layer — bias scoring for deadline-critical crops
            # on expansion tiles. This injects into the existing Phase 2b loop,
            # not a separate planting system.
            exp_priorities = {}
            if next_quadrant is not None and next_quadrant in QUADRANT_UNLOCK_DAYS:
                exp_priorities = expansion_crop_priorities(next_quadrant, day)

            # Phase 2b: Fill remaining empty tiles with best-scoring crops
            for pos in list(empty_tiles):
                best_score, best_crop = -1e9, None
                quadrant = farm.quadrant_of(pos)

                # v5.10: Expansion tranche — priority bias for new quadrant tiles
                if exp_priorities and quadrant in ("SW", "NE") and pos in empty_tiles:
                    for forced_crop, bias in exp_priorities.items():
                        if not _crop_allowed_today(forced_crop, day):
                            continue
                        can_afford = (seeds.get(forced_crop, 0) > 0) or (remaining_money >= CROPS[forced_crop]["seed"])
                        if not can_afford:
                            continue
                        # v5.11: Use dynamic strawberry cap
                        if forced_crop == "STRAWBERRY":
                            cap = get_strawberry_cap(day, len(farm.unlocked) >= 1)
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
                            cap = get_strawberry_cap(day, len(farm.unlocked) >= 1)
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
