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
STARTING_MONEY = 1000
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
PRIORITY_FERT_COLLECT = 80
PRIORITY_BONUS_WATER = 70
PRIORITY_CARE_ANIMAL = 60
PRIORITY_STANDARD_HARVEST = 50
PRIORITY_FERTILIZE_CROP = 48
PRIORITY_PLACE_ANIMAL = 45
PRIORITY_BUILD_STRUCTURE = 75
PRIORITY_PLANT_AND_WATER = 40
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

FEED_WHEAT_BUFFER_DAYS = 2        # keep >= animals * N days of feed wheat
BUY_WHEAT_TRIGGER_DAYS = 1.5

# Phase knobs
PHASE1_WHEAT_TILES = 2            # NW wheat for day-4 cash + animal feed
PHASE1_MELON_TILES_NW = 4
PHASE1_GEESE_DAY0_2 = 6
MELON_PLANT_LAST_DAY_FERT = 17    # last planting that still harvests by 29
MELON_PLANT_LAST_DAY = 19

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
# Portfolio-aware scoring (Fix 3) is the primary diversification mechanism.
CROP_TILE_CAPS = {
    "WHEAT": 99,        # no cap — wheat is the backbone
    "CARROT": 8,        # moderate glut risk
    "TOMATO": 6,        # low yield rate
    "STRAWBERRY": 4,    # slow maturing + extreme glut
    "MELON": 6,         # max 6 tiles (glut threshold ~4-5)
}
FINAL_DUMP_DAYS = {28: 0.75, 29: 0.25}   # min-price fractions loosen at end

# Animal expansion targets (tiles), adjusted dynamically by land/money.
TARGET_GEESE = 18
TARGET_COWS = 3
TARGET_SHEEP = 3
ANIMAL_EXPANSION_HORIZON_DAYS = 14   # ramp projection window
MAX_ANIMAL_BUYS_PER_DAY = 1          # max new animals placed per day

# Diversification discount: fraction of empty tiles assumed for a single crop
# in own-supply glut scoring. Prevents phantom mono-crop over-penalization.
CROP_DIVERSIFICATION_FACTOR = {
    "WHEAT": 0.50, "CARROT": 0.55, "TOMATO": 0.45,
    "STRAWBERRY": 0.35, "MELON": 0.40,
}

# --- market layer (order_builder / market_brain / endgame_liquidator) ------
MIN_CARRY_GAIN = 0.02          # hold only if E[P|+H] exceeds spot by >2%
CARRY_HORIZON_DAYS = 3         # recovery look-ahead for hold decisions
SHED_SOFT_CAP = 80             # start liquidating when shed nears 100 cap
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
    9: 10,   # Day 9: 10 hands (264 actions/day)
    10: 12,  # Days 10-29: 12 hands (312 actions/day)
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
    2: 6,    # Quadrant 2 (NE): buy on day 6
    3: 9,    # Quadrant 3 (SW): buy on day 9
}
QUADRANT_MONEY_THRESHOLDS = {
    2: 1500,  # Need >= $1,500 to buy Q2 ($1,000 land + $500 buffer)
    3: 2450,  # Need >= $2,450 to buy Q3 ($2,000 land + $143 hires + $300 buffer)
}
QUADRANT_HARD_BLOCK = {4}  # NEVER buy quadrant 4 — intensive farming on 75 tiles

# Animal scaling targets by workforce size (hands count)
# Maps hands_count -> (target_geese, target_cows, target_sheep)
# Spec: 4h→4-6 animals; 8h→8-12; 10h→12-16; 12h→16-20. Geese first, then cows, then sheep.
ANIMAL_SCALING = {
    4:  (4, 0, 0),    # Days 0-5: 4 geese
    8:  (8, 2, 0),    # Days 6-8: 8 geese + 2 cows = 10 animals
    10: (10, 3, 1),   # Day 9: 10 geese + 3 cows + 1 sheep = 14 animals
    12: (12, 4, 2),   # Days 10-29: 12 geese + 4 cows + 2 sheep = 18 animals
}

def get_animal_targets(hands):
    """Return (geese, cows, sheep) targets based on current hands count."""
    result = (0, 0, 0)
    for h in sorted(ANIMAL_SCALING.keys()):
        if hands >= h:
            result = ANIMAL_SCALING[h]
    return result

# Sell batch sizes by phase
SELL_BATCH_SIZES = {
    "phase1": 10,  # Days 0-5: sell in batches of 10-20
    "phase2": 5,   # Days 6-8: sell in batches of 5-10
    "phase3": 3,   # Days 9+: sell in batches of 3-5
}
