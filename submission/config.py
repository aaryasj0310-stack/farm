"""Tunable hyperparameters + engine-constant mirror (latest kaggriculture.py).

v5.9: Fixed hiring schedule + action-budget allocator.
All engine facts here are mirrored from the installed kaggle_environments
kaggriculture plugin (CROPS / ANIMALS / MARKET_PARAMS / SHOPS / timings).
"""
import math

# ---------------------------------------------------------------- engine ----
TURNS_PER_DAY = 24
SEASON_DAYS = 30
EPISODE_STEPS = 720
BOARD = 10
SHED_CAPACITY = 100
MAX_MARKET_ORDERS = 10
SHED_ACCESS_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]
FARMER_SPAWN = (4, 4)

CROPS = {
    "WHEAT":      dict(seed=10,  first_yield_day=2,  max_yield_day=4,  interval=0, max_yield=6, ongoing=False, window_start=2),
    "CARROT":     dict(seed=20,  first_yield_day=2,  max_yield_day=3,  interval=0, max_yield=4, ongoing=False, window_start=2),
    "TOMATO":     dict(seed=50,  first_yield_day=8,  max_yield_day=8,  interval=1, max_yield=4, ongoing=True),
    "STRAWBERRY": dict(seed=100, first_yield_day=10, max_yield_day=10, interval=2, max_yield=4, ongoing=True),
    "MELON":      dict(seed=80,  first_yield_day=10, max_yield_day=12, interval=0, max_yield=6, ongoing=False, window_start=6),
}
ANIMALS = {
    "GOOSE": dict(cost=300, structure="COOP",    first_yield_day=4, interval=1, max_held=4, product="EGG"),
    "COW":   dict(cost=400, structure="PASTURE", first_yield_day=8, interval=2, max_held=6, product="MILK"),
    "SHEEP": dict(cost=500, structure="PASTURE", first_yield_day=6, interval=3, max_held=6, product="WOOL"),
}
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
            "EGG", "MILK", "WOOL", "FERTILIZER"]
ANIMAL_LIST = list(ANIMALS)

MARKET_I0 = 10000
STARTING_MONEY = 3000
PRICE_FLOOR = 1
MARKET_PARAMS = {
    "WHEAT":      {"base": 25,  "T": 400, "bf": "sqrt",  "bt": 0.80, "af": "log",    "at": 0.20},
    "CARROT":     {"base": 35,  "T": 450, "bf": "hinge", "bt": 1.00, "af": "sqrt",   "at": 0.70},
    "TOMATO":     {"base": 60,  "T": 200, "bf": "hinge", "bt": 0.40, "af": "sqrt",   "at": 0.60},
    "STRAWBERRY": {"base": 120, "T": 100, "bf": "sqrt",  "bt": 0.70, "af": "linear", "at": 1.60},
    "MELON":      {"base": 250, "T": 300, "bf": "log",   "bt": 0.20, "af": "sq",     "at": 3.60},
    "EGG":        {"base": 50,  "T": 332, "bf": "hinge", "bt": 0.40, "af": "log",    "at": 0.20},
    "MILK":       {"base": 160, "T": 122, "bf": "sqrt",  "bt": 0.60, "af": "linear", "at": 1.60},
    "WOOL":       {"base": 200, "T": 105, "bf": "log",   "bt": 0.20, "af": "sq",     "at": 3.20},
    "FERTILIZER": {"base": 100, "T": 200, "bf": "linear","bt": 0.40, "af": "linear", "at": 0.40},
}
SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
LAND_ORDER = ["NE", "SW"]        # drop SE (hard cap at 3 quadrants: NW + NE + SW = 75 tiles)
LAND_PRICES = [1000, 2000]       # drop $4,000 SE price

# ------------------------------------------------------------- priorities ---
PRIORITY_URGENT_SURVIVAL = 100
PRIORITY_DECAY_HARVEST = 90
PRIORITY_FEED_STAGING = 86       # PICKUP wheat so upcoming FEEDs can execute
PRIORITY_PROD_DAY_FEED = 85
PRIORITY_FERT_COLLECT = 75       # daily $100 cash per animal; elevated priority
PRIORITY_PLANT_AND_WATER = 75    # plant seeds early so crops get full-day growth
PRIORITY_BONUS_WATER = 70
PRIORITY_CARE_ANIMAL = 65        # multiplies cow/sheep yield to 6/3 and 6/4; daily care essential
PRIORITY_STANDARD_HARVEST = 65
PRIORITY_PLACE_ANIMAL = 84       # immediate pickup and placement of purchased livestock
PRIORITY_BUILD_STRUCTURE = 78     # build planned pastures so animals can be placed without delay
PRIORITY_FERTILIZE_CROP = 60
PRIORITY_WEED_DIG = 20

# ------------------------------------------------------------- policy -------
# Latest engine: care banks +1 on EVERY fed+cared day and goose produces
# daily, so caring a goose nets +1 egg/day for one action -> CARE ALL.
CARE_GEESE = True

# Market timing: town shops consume on global steps where step % 4 == 0 and
# the center on step % 24 == 0; prices refresh right after consumption.
# Selling at hours t % 4 == 1 quotes post-drain boosted prices.
SELL_WINDOWS = [1, 5, 9, 13, 17, 21]
SELL_HOUR_SET = set(SELL_WINDOWS)

# Drip-selling thresholds: keep realized price >= fraction of current spot.
DRIP_PRICE_KEEP_FRAC = {           # per-product keep-fraction while slicing
    "MELON": 0.90, "STRAWBERRY": 0.88, "MILK": 0.85,
    "WOOL": 0.90, "EGG": 0.97, "WHEAT": 0.95,
    "CARROT": 0.95, "TOMATO": 0.93, "FERTILIZER": 0.90,
}
HOLD_AT_FLOOR_PRODUCTS = {"MELON", "STRAWBERRY", "MILK", "WOOL"}

FEED_WHEAT_BUFFER_DAYS = 4        # keep >= animals * 4 days of feed wheat (bridges 4-day wheat cycle)
BUY_WHEAT_TRIGGER_DAYS = 2.0

# Phase knobs
PHASE1_WHEAT_TILES = 8            # NW wheat for day-4 cash + animal feed (Leader heuristic)
PHASE1_MELON_TILES_NW = 12        # NW melons for day-10 cash surge (Leader springboard)
PHASE1_GEESE_DAY0_2 = 0            # Zero Geese policy: geese produce low-margin down, zero fertilizer
MELON_PLANT_LAST_DAY_FERT = 17    # last planting that still harvests by 29
MELON_PLANT_LAST_DAY = 19

# Stage 8B Phase 1E: C2 Adaptive Zonal Dispatch
C2_MAX_SPILLOVER_DIST = 12         # Max Manhattan distance allowed for cross-quadrant spillover
C2_SPILLOVER_PRIORITY_FLOOR = 20   # Minimum task priority eligible for cross-quadrant dispatch

EFFECTIVE_ACTIONS_PER_UNIT = 12
MIN_HANDS_BASE = 4
HIRE_BUDGET_MAX_HANDS = 7
ENDGAME_START_DAY = 28
ANIMAL_FEED_CUTOFF_DAY = 29     # feeding active Days 0–28; disabled Day 29
ANIMAL_CARE_CUTOFF_DAY = 29     # care active Days 0–28; disabled Day 29

# ROI-based land expansion
LAND_ROI_THRESHOLD = 1.5       # minimum lifetime_profit / price ratio
LAND_BUY_LAST_DAY = 20         # hard cutoff — land bought after Day 20 can't pay back

# Static crop caps — safety net to prevent monoculture if scoring has bugs.
# Portfolio-aware scoring is the primary diversification mechanism.
CROP_TILE_CAPS = {
    "WHEAT": 99,        # no cap — wheat is the backbone
    "CARROT": 16,       # diversified cash crop
    "TOMATO": 16,       # high value ongoing
    "STRAWBERRY": 20,   # high value ongoing (expanded for leader-style production)
    "MELON": 12,        # max 12 tiles (leader-style early high-value harvest)
}
FINAL_DUMP_DAYS = {28: 0.75, 29: 0.25}   # min-price fractions loosen at end

# Animal expansion targets (tiles), adjusted dynamically by land/feed/labor/money.
TARGET_GEESE = 0
TARGET_COWS = 6
TARGET_SHEEP = 12
ANIMAL_EXPANSION_HORIZON_DAYS = 14   # ramp projection window
MAX_ANIMAL_BUYS_PER_DAY = 2          # max new animals placed per day

# Diversification discount: fraction of empty tiles assumed for a single crop
# in own-supply glut scoring. Prevents phantom mono-crop over-penalization.
CROP_DIVERSIFICATION_FACTOR = {
    "WHEAT": 0.50, "CARROT": 0.55, "TOMATO": 0.45,
    "STRAWBERRY": 0.35, "MELON": 0.40,
}

# --- market layer (order_builder / market_brain / endgame_liquidator) ------
MIN_CARRY_GAIN = 0.02          # hold only if E[P|+H] exceeds spot by >2%
CARRY_HORIZON_DAYS = 3         # recovery look-ahead for hold decisions
SHED_SOFT_CAP = 65             # start emergency liquidation when shed reaches 65 (Leader heuristic)
SHED_RESUME_CAP = 55           # resume normal sell windows once shed falls <= 55
MELON_SEASON_SALE_CAP = 150    # maximum cumulative melons to sell before quadratic price cliff
ENDGAME_RISK_DAYS = 3          # days_left below this => aggressive dumping
FLOOR_HOLD_MIN_DAYS_LEFT = 5   # hold $1-floored stock only if recovery time
MIN_SLICE_QTY = 1              # smallest sell slice per product per window
SELL_SLOT_SHARE = 0.6          # fraction of the 10-order cap for sells
WHEAT_BUY_PRICE_BUFFER = 1.10  # BUY_PRODUCT quote drifts up as we buy
MONEY_RESERVE_DEFAULT = 300

DEBUG = False


def log(msg):
    if DEBUG:
        print(f"[agent] {msg}")


# ====================================================================
# v5.9: Fixed Hiring Schedule + Land Policy
# ====================================================================

# Fixed hiring schedule — NEVER override with money/market conditions.
# Key = day range start, Value = hands count to hire each morning.
# Engine resets farm["hands"] to [] daily; must re-hire every day.
# Cost per day: 4h=$7, 8h=$54, 10h=$143, 12h=$376 (fibonacci pricing).
DAY_TO_HANDS = {
    0: 4,    # Days 0-5: 4 hands (120 actions/day)
    6: 8,    # Days 6-8: 8 hands (216 actions/day)
    9: 8,    # Day 9: 8 hands ($54/day) - saves $89 on SW unlock day
    10: 10,  # Day 10: 10 hands ($143/day)
    11: 12,  # Days 11-29: 12 hands ($376/day)
    30: 0,   # Day 30: 0 hands (main farmer only)
}

def get_target_hands(day):
    """Return the target hired-hands count for a given day."""
    result = 0
    for start_day in sorted(DAY_TO_HANDS.keys()):
        if day >= start_day:
            result = DAY_TO_HANDS[start_day]
    return result

def get_actions_available(day):
    """Total actions available per day given the fixed schedule."""
    hands = get_target_hands(day)
    total_units = 1 + hands  # farmer + hired hands
    return total_units * TURNS_PER_DAY

# Land purchase policy — fixed days and money thresholds.
# Quadrant numbering: NW=1 (starting), NE=2 ($1k), SW=3 ($2k), SE=4 ($4k)
# Strategy: Only buy quadrants 1-3 (75 tiles). NEVER buy quadrant 4.
QUADRANT_UNLOCK_DAYS = {
    2: 3,    # Quadrant 2 (NE): buy on days 3-5 (Leader heuristic: cash >= 1400)
    3: 9,    # Quadrant 3 (SW): buy on day 9 (pre-buy day 8)
}
QUADRANT_MONEY_THRESHOLDS = {
    2: 1400,  # Need >= $1,400 to buy Q2 ($1,000 land + $400 seed/ops float)
    3: 2204,  # Need >= $2,204 to buy Q3 ($2,000 land + $150 escrow + $54 hires)
}
QUADRANT_HARD_BLOCK = {4}  # NEVER buy quadrant 4 — intensive farming on 75 tiles

# ====================================================================
# v5.10: Expansion Planner — deadline-aware land + seed pre-purchase
# ====================================================================

# Absolute planting deadlines (last valid day to plant for full harvest by day 29)
STRAWBERRY_PLANT_DEADLINE = 13   # last_harvest = 10 + 3*2 = 16; 29-16=13
MELON_PLANT_DEADLINE = 17        # max_yield_day=12; 29-12=17

# Seed pre-purchase lead days (buy seeds N days before land unlock)
PRE_BUY_LEAD_DAYS = 1

# SW expansion seed targets & geometry constants
SW_ESCROW_AMOUNT = 150           # 15 wheat seeds * $10 (Rule P1)
PORT_SW = (4, 5)                 # Shed-access tile inside SW; squad anchor
SW_SOIL_TILES = {(x, y) for x in range(5) for y in range(7, 10)}  # 15 tiles (rows 7,8,9)
SW_PASTURE_TILES = {(x, 5) for x in range(4)} | {(x, 6) for x in range(5)}  # 9 tiles (rows 5,6)

SW_SEED_TARGETS = {
    "WHEAT": 15,                 # strictly WHEAT for animal feed engine (Rule P5)
}
NE_SEED_TARGETS = {
    "CARROT": 8,                 # fast cash crop for NE
    "TOMATO": 4,                 # secondary ongoing crop
}

# SW treasury seed cost: exactly the $150 escrow
SW_TREASURY_SEED_COST = 150

# ====================================================================
# v5.11: Dynamic strawberry cap — deadline-consistent
# ====================================================================

def get_strawberry_cap(day, land_purchased=False):
    """Time-varying strawberry cap: 16 → 18 → 20 (Day 13 only) → 0.

    Rationale:
    - Day 0-8: Expanding (16) — early season in NW/NE
    - Day 9-12: Aggressive (18) — SW expanding production
    - Day 13: Maximum (20) — last day to plant strawberry (deadline)
    - Day 14+: Zero (0) — deadline passed, no new strawberry planting
    """
    if not land_purchased:
        return 0
    if day <= 8:
        return 16
    elif day <= 12:
        return 18
    elif day == 13:
        return 20
    else:
        return 0


# ====================================================================
# v5.11 / v6.0: SW seed targets — Whitelist & Transition
# ====================================================================

def get_sw_seed_targets(day, money=0, land_cost=2000):
    """SW seed targets: strictly WHEAT (D9-24) and CARROT (D25-27).

    Rule P5: Eliminates strawberry/tomato capital trap and Day 13 lockout.
    """
    if day <= 24:
        return {"WHEAT": 15}
    elif day <= 27:
        return {"CARROT": 15}
    else:
        return {}

# Animal scaling targets by workforce size (hands count)
# Maps hands_count -> (target_geese, target_cows, target_sheep)
# Animal scaling targets by workforce size (hands count)
# Maps hands_count -> (target_geese, target_cows, target_sheep)
ANIMAL_SCALING = {
    4:  (0, 2, 2),    # Days 0-5: 2 cows + 2 sheep (leader opening)
    8:  (0, 4, 4),    # Days 6-8: 4 cows + 4 sheep = 8 animals
    10: (0, 5, 8),    # Day 9: 5 cows + 8 sheep = 13 animals
    12: (0, 6, 12),   # Days 10-29: 6 cows + 12 sheep = 18 animals
}

# Stage 8B Phase 1A: C4 — Late-Game Livestock Investment Cap
# Stage 8A empirical cutoff boundary: Day 12. Animals purchased Day 12+ fail to amortize
# capital cost, pasture build cost, feed procurement, and care opportunity costs.
C4_LIVESTOCK_CUTOFF_DAY = 12

def get_animal_targets(day=None, money=None, shed_wheat=None, current_animals=None, max_pastures=20, hands=None):
    """Return animal targets. Supports both legacy hands count signature and full Astra heuristic."""
    if hands is not None:
        result = (0, 0, 0)
        for h in sorted(ANIMAL_SCALING.keys()):
            if hands >= h:
                result = ANIMAL_SCALING[h]
        return result
    if money is not None:
        from strategy.animal_planner import get_animal_targets as _astra_targets
        return _astra_targets(day, money, shed_wheat, current_animals, max_pastures=max_pastures)
    if day is not None and isinstance(day, int) and day in ANIMAL_SCALING:
        result = (0, 0, 0)
        for h in sorted(ANIMAL_SCALING.keys()):
            if day >= h:
                result = ANIMAL_SCALING[h]
        return result
    from strategy.animal_planner import get_animal_targets as _astra_targets
    return _astra_targets(day or 0, money or 0, shed_wheat or 0, current_animals or {}, max_pastures=max_pastures)

# Sell batch sizes by phase
SELL_BATCH_SIZES = {
    "phase1": 10,  # Days 0-5: sell in batches of 10-20
    "phase2": 5,   # Days 6-8: sell in batches of 5-10
    "phase3": 3,   # Days 9+: sell in batches of 3-5
}
