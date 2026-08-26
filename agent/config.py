"""Tunable hyperparameters + engine-constant mirror (latest kaggriculture.py).

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
LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]

# ------------------------------------------------------------- priorities ---
PRIORITY_URGENT_SURVIVAL = 100
PRIORITY_DECAY_HARVEST = 90
PRIORITY_FEED_STAGING = 86       # PICKUP wheat so upcoming FEEDs can execute
PRIORITY_PROD_DAY_FEED = 85
PRIORITY_FERT_COLLECT = 80
PRIORITY_BONUS_WATER = 70
PRIORITY_CARE_ANIMAL = 60
PRIORITY_STANDARD_HARVEST = 50
PRIORITY_PLACE_ANIMAL = 45
PRIORITY_PLANT_AND_WATER = 40
PRIORITY_BUILD_STRUCTURE = 35
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
PHASE1_MELON_TILES_NW = 15
PHASE1_GEESE_DAY0_2 = 6
BUY_LAND_NE_DAY = 6               # melons planted day<=7 still get 2 cycles
BUY_LAND_SW_MIN_BANK = 2600
BUY_LAND_SE_MIN_BANK = 5200
MELON_PLANT_LAST_DAY_FERT = 17    # last planting that still harvests by 29
MELON_PLANT_LAST_DAY = 19

HIRE_BUDGET_MAX_HANDS = 7
ENDGAME_START_DAY = 28
FINAL_DUMP_DAYS = {28: 0.75, 29: 0.25}   # min-price fractions loosen at end

# Animal expansion targets (tiles), adjusted dynamically by land/money.
TARGET_GEESE = 18
TARGET_COWS = 3
TARGET_SHEEP = 3

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
