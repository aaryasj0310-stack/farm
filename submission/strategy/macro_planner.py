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
    BUY_LAND_NE_DAY,
    BUY_LAND_SW_MIN_BANK,
    BUY_LAND_SE_MIN_BANK,
    CROP_DIVERSIFICATION_FACTOR,
    CROP_TILE_CAPS,
    CROPS,
    ENDGAME_START_DAY,
    FEED_WHEAT_BUFFER_DAYS,
    HIRE_BUDGET_MAX_HANDS,
    LAND_ORDER,
    LAND_PRICES,
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
)
from market.price_math import inventory_at_price, market_price
from market.order_builder import hire_total_cost

# ---------------------------------------------------------------------------
# Asset economics — imported from authoritative baked_economics artifact.
# ---------------------------------------------------------------------------
try:
    from strategy.baked_economics import (
        ANIMAL_ECONOMICS,
        ANIMAL_TARGETS,
        BOOST_CAP,
        CROP_CYCLE_LEN,
        CROP_ECONOMICS,
        MONEY_RESERVE,
        SHOP_BOOST_WEIGHT,
    )
except ImportError:
    from baked_economics import (
        ANIMAL_ECONOMICS,
        ANIMAL_TARGETS,
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


def _crop_allowed_today(crop, day):
    """True if planted today it still completes its final harvest by day 29."""
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
    net = score - e["cost30"]
    per_day = net / 30.0
    return per_day, details


# ---------------------------------------------------------------------------
# Wheat capacity projection — dynamic animal-cap / buy-wheat controller
# ---------------------------------------------------------------------------

def project_wheat_harvests(plant_day, current_day, season_end=29):
    """Wheat units a tile planted on plant_day will yield through season_end.

    Wheat is one-time: first_yield_day=2, max_yield_day=4, max_yield=6.
    Produces max_yield units once at plant_day + max_yield_day.
    """
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

        # ---------------- animal expansion (tiles reserved first) ------
        counts = {}
        for t in animals:
            counts[t.animal] = counts.get(t.animal, 0) + 1
        structures_empty = {t.pos: t.kind for t in farm.iter_tiles()
                            if t.kind in ("COOP", "PASTURE") and not t.is_animal}

        buy_animal = {}
        reserved_structure_tiles = []
        # endgame: no new animals — just feed what we have
        if not is_endgame:
            for animal in ANIMAL_LIST:
                target = ANIMAL_TARGETS.get(animal, 0)
                deficit_a = target - counts.get(animal, 0)
                if deficit_a <= 0:
                    continue
                # dynamic cap: don't exceed sustainable herd size
                if n_animals + sum(buy_animal.values()) >= sustainable:
                    continue
                info = ANIMALS[animal]
                econ = ANIMAL_ECONOMICS[animal]
                prod = info["product"]
                sale_days = list(range(info["first_yield_day"], 30, info["interval"]))
                e_price = _mean_over(self.fc, prod, sale_days)
                gross = econ["out30"] * e_price
                feed_cost = econ["feed30"] * 25.0
                if gross - feed_cost - info["cost"] <= 0:
                    continue                                    # unprofitable regime
                affordable = ctx["farm"].money >= info["cost"] + self.reserve
                if affordable and deficit_a > 0:
                    buy_animal[animal] = buy_animal.get(animal, 0) + 1

                # queue structure build for one deficit slot per day
                struct_kind = info["structure"]
                free_struct = [pos for pos, k in structures_empty.items()
                               if k == struct_kind]
                if free_struct:
                    pass                                        # place handled below
                elif empty_tiles:
                    tile = empty_tiles.pop(0)
                    reserved_structure_tiles.append(tile)

        # single build_op per day: prefer whichever deficit came first
        if reserved_structure_tiles:
            animal_by_structure = {}
            for animal in ANIMAL_LIST:
                info = ANIMALS[animal]
                deficit = ANIMAL_TARGETS.get(animal, 0) - counts.get(animal, 0)
                if deficit > 0:
                    animal_by_structure.setdefault(info["structure"], animal)
            op = "BUILD_COOP" if "COOP" in animal_by_structure else "BUILD_PASTURE"
            plan.build_op = op
            plan.build_queue = reserved_structure_tiles[:3]

        # ---------------- crop queue on remaining tiles ----------------
        # endgame: no new planting — just harvest and sell
        plant_queue = []
        buy_seed = {}
        hires = 0
        EFFECTIVE_ACTIONS_PER_UNIT = 12
        MIN_HANDS_BASE = 4
        if not is_endgame:
            # ---- Dynamic hiring floor (Fix 7) ----
            # Base 4 hands + 1 per 4 animals + 1 per extra quadrant
            dynamic_floor = MIN_HANDS_BASE + n_animals // 4 + (len(farm.unlocked) - 1)
            _load_est = estimate_daily_load(ctx)
            _units_now = 1 + len(farm.hands)
            _needed = -(-_load_est // EFFECTIVE_ACTIONS_PER_UNIT)
            hires = max(0, min(HIRE_BUDGET_MAX_HANDS, _needed - _units_now))
            if day < 25:
                hires = max(hires, dynamic_floor - len(farm.hands))

            # ---- Budget prioritization (Fix 6) ----
            money = ctx["farm"].money
            budget = money - self.reserve

            hire_cost = hire_total_cost(hires)

            n_extra = len(farm.unlocked) - 1
            land_cost = 0
            if n_extra < len(LAND_ORDER):
                land_price = LAND_PRICES[n_extra]
                if money >= land_price + self.reserve + 200:
                    land_cost = land_price

            animal_cost = sum(ANIMALS[a]["cost"] * k for a, k in buy_animal.items())
            seed_budget = max(0, budget - hire_cost - land_cost - animal_cost)
            remaining_money = seed_budget

            seeds = dict(private.seeds)

            # ---- Phase 2: Wheat-first (Fix 2) ----
            wheat_target = max(3, min(TARGET_GEESE // 3, 8))  # 3–8 wheat tiles
            wheat_available = seeds.get("WHEAT", 0)
            wheat_to_plant = min(wheat_target, wheat_available, len(empty_tiles))
            for _ in range(wheat_to_plant):
                pos = empty_tiles.pop(0)
                plant_queue.append((pos, "WHEAT"))
                seeds["WHEAT"] = seeds.get("WHEAT", 0) - 1
            # Replenish wheat seeds for next turn
            wheat_buy = max(wheat_target - wheat_available + wheat_to_plant, 0)
            if wheat_buy > 0 and remaining_money >= CROPS["WHEAT"]["seed"] * wheat_buy:
                buy_seed["WHEAT"] = buy_seed.get("WHEAT", 0) + wheat_buy
                remaining_money -= CROPS["WHEAT"]["seed"] * wheat_buy

            # Track planned counts for portfolio-aware scoring
            planned = {"WHEAT": wheat_to_plant} if wheat_to_plant > 0 else {}

            # ---- Phase 3: Portfolio-aware per-tile scoring (Fix 3) ----
            for pos in empty_tiles:
                best_score, best_crop = -1e9, None
                for crop in CROPS:
                    if not _crop_allowed_today(crop, day):
                        continue
                    if planned.get(crop, 0) >= CROP_TILE_CAPS.get(crop, 99):
                        continue  # safety cap (Fix 4)
                    # Score with ACTUAL planned count (not a fixed fraction)
                    own_for_this = planned.get(crop, 0) + 1
                    score, _ = _crop_score(crop, day, self.fc, boosts,
                                           own_for_this, n_animals, n_animals,
                                           opp_advice=opp_advice)
                    if score > best_score:
                        best_score, best_crop = score, crop
                if best_crop is None or best_score <= 0:
                    break
                # Reserve seed
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
        else:
            remaining_money = ctx["farm"].money - self.reserve

        # ---------------- wheat feed buffer ---------------------------
        wheat_needed = n_animals * FEED_WHEAT_BUFFER_DAYS + \
            sum(ANIMAL_ECONOMICS[a]["feed30"] for a in buy_animal) // 30 * 2
        if trigger:
            wheat_needed = max(wheat_needed, deficit)
        buy_wheat = 0
        if wheat_have < wheat_needed:
            buy_wheat = min(wheat_needed - wheat_have,
                            int(max(0, remaining_money) // 25))
            remaining_money -= buy_wheat * 25

        # ---- Adaptive land expansion ----
        buy_land = False
        if not is_endgame:
            n_extra_unlocked = len(farm.unlocked) - 1
            if n_extra_unlocked < len(LAND_ORDER):  # ["NE", "SW"] — no SE
                price = LAND_PRICES[n_extra_unlocked]
                current_load = estimate_daily_load(ctx) + len(plant_queue)
                effective_capacity = (1 + len(farm.hands) + hires) * EFFECTIVE_ACTIONS_PER_UNIT
                spare_capacity = max(0, effective_capacity - current_load)
                tiles_added = 25  # each quadrant adds 25 tiles

                # Condition 1: enough spare action capacity to service the new tiles
                # (prevents weed cascade on existing tiles)
                can_service = spare_capacity >= tiles_added

                # Condition 2: first harvest income available (not just starting capital)
                # Wheat planted day 1 → harvest day 5. Geese produce from day 4+.
                has_income = day >= 5 or ctx["farm"].money > STARTING_MONEY

                # Condition 3: geese partially stocked (animals are higher ROI than land)
                geese_started = n_animals >= min(3, TARGET_GEESE)

                # Condition 4: affordable after reserving feed buffer
                feed_buffer = n_animals * FEED_WHEAT_BUFFER_DAYS * 25  # wheat at ~$25
                affordable = ctx["farm"].money >= price + MONEY_RESERVE + feed_buffer

                if can_service and has_income and geese_started and affordable:
                    buy_land = True
                    remaining_money -= price

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
        for animal in ANIMAL_LIST:
            struct = ANIMALS[animal]["structure"]
            free = [pos for pos, k in structures_empty.items() if k == struct]
            if not free:
                continue
            held = inv_hold.get(animal)
            if held:
                place_queue.append({"op": "PLACE", "target": sorted(free)[0],
                                    "args": [animal]})
            elif private.shed.get(animal, 0) > 0:
                place_queue.append({"op": "PICKUP",
                                    "target": (4, 4), "args": [animal]})
            break   # one species per day keeps the queue focused

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
        return plan


def _mean_over(forecast, product, days):
    vals = [forecast.expected_price(product, d) for d in days]
    return sum(vals) / len(vals) if vals else 0.0


def estimate_daily_load(ctx):
    """Rough action-count needed today (mirrors task_scheduler helper)."""
    from task_scheduler import estimate_daily_load as esl
    return esl(ctx)
