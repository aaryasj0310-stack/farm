from __future__ import annotations
import os
import sys
import math
import json
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set

"""Tunable hyperparameters + engine-constant mirror (latest kaggriculture.py).

v5.9: Fixed hiring schedule + action-budget allocator.
All engine facts here are mirrored from the installed kaggle_environments
kaggriculture plugin (CROPS / ANIMALS / MARKET_PARAMS / SHOPS / timings).
"""


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
    "CARROT": 16,       # diversified cash crop
    "TOMATO": 14,       # high value
    "STRAWBERRY": 10,   # high value + fertilizer
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

# ===========================================================================
# END MODULE: config.py
# ===========================================================================

"""Baked asset economics artifact.

Authoritative source of season-long yield, cost, and lifecycle metrics
derived from simulations/profitability_calculator. Consumed by MacroPlanner
and validation test suites to eliminate mirror-drift footguns.
"""


# ---------------------------------------------------------------------------
# Crop economics: season yield, baseline cost, fertilizer application count
# ---------------------------------------------------------------------------
CROP_ECONOMICS = {
    # crop: (season_yield_30d, season_cost_30d, fert_apps_per_cycle)
    "WHEAT":      dict(yield30=24.0, cost30=60.0,  apps=0),
    "CARROT":     dict(yield30=21.0, cost30=160.0, apps=0),
    "TOMATO":     dict(yield30=16.0, cost30=100.0 + 200.0, apps=2),   # 2 plantings x 2 apps
    "STRAWBERRY": dict(yield30=8.0,  cost30=200.0 + 200.0, apps=2),
    "MELON":      dict(yield30=24.0, cost30=240.0 + 100.0, apps=1),   # fert variant wins (4th cycle)
}

CROP_CYCLE_LEN = {  # replant period (harvest day + 1)
    "WHEAT": 5, "CARROT": 4, "MELON": 9, "TOMATO": 12, "STRAWBERRY": 17,
}

# ---------------------------------------------------------------------------
# Animal economics: purchase cost, care-enabled 30d output, 30d feed demand
# ---------------------------------------------------------------------------
ANIMAL_ECONOMICS = {
    # product output assumes care enabled (latest engine: bank applies daily)
    "GOOSE": dict(cost=300, out30=52.0, feed30=30, structure="COOP"),
    "COW":   dict(cost=400, out30=22.0, feed30=30, structure="PASTURE"),
    "SHEEP": dict(cost=500, out30=24.0, feed30=30, structure="PASTURE"),
}

ANIMAL_TARGETS = {
    "GOOSE": TARGET_GEESE,
    "COW": TARGET_COWS,
    "SHEEP": TARGET_SHEEP,
}

MONEY_RESERVE = 300          # kept back for hires/feed surprises
SHOP_BOOST_WEIGHT = 0.15     # E[P] lift per shop instance demanding a crop
BOOST_CAP = 1.6

# ===========================================================================
# END MODULE: strategy/baked_economics.py
# ===========================================================================

# Auto-generated by price_forecast.py --build-table. Do not edit.
PRICE_TABLE = {'version': 1,
 'scenario': 'town_only',
 'complete_enumeration': True,
 'count': 16777216,
 'days': 30,
 'products': ['WHEAT',
              'CARROT',
              'TOMATO',
              'STRAWBERRY',
              'MELON',
              'EGG',
              'MILK',
              'WOOL',
              'FERTILIZER'],
 'mean': {'WHEAT': [26.0,
                    26.0,
                    27.0,
                    27.625,
                    28.25,
                    28.875,
                    30.1094,
                    30.5,
                    31.3594,
                    32.2188,
                    32.7852,
                    33.5566,
                    34.5786,
                    35.3611,
                    35.9861,
                    36.9114,
                    37.6668,
                    38.3056,
                    39.2564,
                    40.0374,
                    40.9002,
                    41.5714,
                    42.357,
                    43.1703,
                    44.0105,
                    44.771,
                    45.5597,
                    46.235,
                    46.983,
                    47.625],
          'CARROT': [35.0,
                     35.0,
                     35.0,
                     35.25,
                     35.375,
                     35.625,
                     36.5625,
                     37.0312,
                     37.3125,
                     38.0156,
                     38.5898,
                     39.1387,
                     39.8542,
                     40.6003,
                     41.4016,
                     42.3397,
                     43.2451,
                     44.1821,
                     45.3253,
                     46.6236,
                     47.8531,
                     49.4005,
                     51.0603,
                     52.921,
                     55.3845,
                     58.2607,
                     61.6799,
                     65.7201,
                     70.446,
                     75.9932],
          'TOMATO': [60.0,
                     60.0,
                     60.0,
                     60.25,
                     61.25,
                     61.5,
                     61.9375,
                     62.25,
                     62.5625,
                     63.25,
                     63.9375,
                     64.5781,
                     65.6211,
                     66.4062,
                     67.1914,
                     68.2676,
                     69.2939,
                     70.4268,
                     71.9927,
                     73.8335,
                     76.2659,
                     79.46,
                     83.4132,
                     88.3453,
                     94.8778,
                     102.785,
                     112.1626,
                     123.1649,
                     135.9722,
                     150.6252],
          'STRAWBERRY': [128.0,
                         132.0,
                         135.0,
                         142.0,
                         147.0,
                         151.0,
                         157.5,
                         163.25,
                         168.0,
                         174.625,
                         180.25,
                         185.375,
                         191.875,
                         197.8125,
                         203.125,
                         209.4062,
                         215.375,
                         220.8125,
                         227.0781,
                         233.0625,
                         238.6094,
                         244.9219,
                         250.8516,
                         256.5703,
                         262.6758,
                         268.6289,
                         274.2461,
                         279.7852,
                         285.0859,
                         290.2266],
          'MELON': [256.0,
                    260.0,
                    262.0,
                    264.0,
                    266.0,
                    267.0,
                    268.0,
                    269.0,
                    270.0,
                    271.0,
                    272.0,
                    272.0,
                    273.0,
                    274.0,
                    274.0,
                    275.0,
                    275.0,
                    276.0,
                    276.0,
                    277.0,
                    277.0,
                    277.0,
                    278.0,
                    278.0,
                    279.0,
                    279.0,
                    279.0,
                    280.0,
                    280.0,
                    280.0],
          'EGG': [50.0,
                  50.0,
                  50.0,
                  50.25,
                  50.25,
                  50.25,
                  50.6875,
                  50.75,
                  51.75,
                  51.8125,
                  52.0625,
                  52.5,
                  52.7656,
                  53.3906,
                  53.5273,
                  54.0947,
                  54.7373,
                  55.1436,
                  55.7925,
                  56.251,
                  56.9824,
                  57.6523,
                  58.3005,
                  59.1916,
                  60.1965,
                  61.3442,
                  62.5763,
                  64.0339,
                  65.8197,
                  67.7321],
          'MILK': [169.0,
                   172.0,
                   175.0,
                   180.75,
                   185.375,
                   189.25,
                   194.9531,
                   200.1406,
                   204.0,
                   209.8984,
                   214.998,
                   219.5605,
                   224.9939,
                   230.251,
                   234.9636,
                   240.7092,
                   245.7624,
                   250.73,
                   256.3484,
                   261.5906,
                   266.672,
                   272.2042,
                   277.3145,
                   282.446,
                   287.983,
                   293.2526,
                   298.2901,
                   303.2775,
                   307.8982,
                   312.5342],
          'WOOL': [206.0,
                   209.0,
                   212.0,
                   215.25,
                   216.75,
                   218.875,
                   221.0156,
                   222.375,
                   223.7188,
                   225.459,
                   226.2012,
                   227.3125,
                   228.9038,
                   229.5964,
                   230.7896,
                   231.7118,
                   232.8603,
                   233.4416,
                   234.673,
                   235.324,
                   236.4019,
                   237.022,
                   237.6503,
                   238.5348,
                   239.2275,
                   239.7965,
                   240.6191,
                   241.1659,
                   241.5134,
                   241.7739],
          'FERTILIZER': [100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0,
                         100.0]},
 'std': {'WHEAT': [0.0,
                   0.0,
                   0.0,
                   0.4841,
                   0.9682,
                   1.4524,
                   1.1874,
                   1.5309,
                   1.7798,
                   1.8789,
                   1.9195,
                   2.1948,
                   2.1486,
                   2.2641,
                   2.4135,
                   2.4374,
                   2.5125,
                   2.6801,
                   2.6749,
                   2.756,
                   2.8501,
                   2.8688,
                   2.9479,
                   3.0265,
                   3.0682,
                   3.1249,
                   3.184,
                   3.2755,
                   3.3425,
                   3.4299],
         'CARROT': [0.0,
                    0.0,
                    0.0,
                    0.433,
                    0.696,
                    1.111,
                    1.1163,
                    1.5306,
                    1.9675,
                    2.5586,
                    3.0631,
                    3.6366,
                    4.1998,
                    4.7824,
                    5.3808,
                    6.0105,
                    6.6723,
                    7.3508,
                    8.1001,
                    8.8458,
                    10.0803,
                    11.9129,
                    14.4832,
                    18.0189,
                    22.8478,
                    28.9501,
                    36.3965,
                    45.2766,
                    55.6116,
                    67.4134],
         'TOMATO': [0.0,
                    0.0,
                    0.0,
                    0.433,
                    0.433,
                    0.866,
                    1.2484,
                    1.7854,
                    2.0907,
                    2.5617,
                    3.1617,
                    3.6435,
                    3.9687,
                    4.4677,
                    5.0535,
                    5.6164,
                    6.5841,
                    7.8903,
                    10.0152,
                    13.2585,
                    17.6396,
                    24.011,
                    32.0516,
                    41.846,
                    54.0859,
                    68.3782,
                    84.8152,
                    103.4156,
                    124.1082,
                    146.9383],
         'STRAWBERRY': [0.0,
                        0.0,
                        0.0,
                        5.0,
                        8.0,
                        10.0,
                        11.9269,
                        13.442,
                        15.5724,
                        16.3779,
                        17.8308,
                        19.3516,
                        20.1273,
                        21.3255,
                        22.31,
                        23.0758,
                        23.8534,
                        24.8451,
                        25.4701,
                        26.2862,
                        27.1636,
                        27.7378,
                        28.3505,
                        29.0626,
                        29.6474,
                        30.1975,
                        30.8085,
                        31.5382,
                        32.3218,
                        33.0144],
         'MELON': [0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0,
                   0.0],
         'EGG': [0.0,
                 0.0,
                 0.0,
                 0.433,
                 0.433,
                 0.433,
                 0.8455,
                 0.9682,
                 0.9682,
                 1.1302,
                 1.4238,
                 1.6202,
                 1.9525,
                 2.2818,
                 2.4477,
                 2.9305,
                 3.198,
                 3.6261,
                 3.7761,
                 4.1343,
                 4.5574,
                 4.9877,
                 5.603,
                 6.3025,
                 7.3916,
                 9.0442,
                 11.2011,
                 13.9961,
                 17.3034,
                 21.3641],
         'MILK': [0.0,
                  0.0,
                  0.0,
                  4.8412,
                  8.2301,
                  10.6507,
                  12.0486,
                  14.0021,
                  16.1439,
                  17.7613,
                  19.058,
                  20.9201,
                  22.0053,
                  23.1409,
                  24.548,
                  25.5975,
                  26.5954,
                  27.9321,
                  28.7916,
                  29.696,
                  30.7464,
                  31.4459,
                  32.3235,
                  33.197,
                  33.9561,
                  34.667,
                  35.5448,
                  36.2755,
                  37.1828,
                  38.0106],
         'WOOL': [0.0,
                  0.0,
                  0.0,
                  3.3072,
                  4.6301,
                  4.9608,
                  5.8803,
                  6.301,
                  6.8544,
                  7.0233,
                  7.7707,
                  7.8628,
                  7.8849,
                  8.4452,
                  8.5258,
                  8.848,
                  8.7978,
                  9.2232,
                  8.9319,
                  9.2077,
                  9.1879,
                  9.3147,
                  9.5697,
                  9.3468,
                  9.4956,
                  9.6585,
                  9.3518,
                  9.6674,
                  9.8173,
                  9.9474],
         'FERTILIZER': [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0]},
 'floor_prob': {'WHEAT': [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                'CARROT': [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0],
                'TOMATO': [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0],
                'STRAWBERRY': [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                'MELON': [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                'EGG': [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0],
                'MILK': [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                'WOOL': [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                'FERTILIZER': [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0]},
 'quantiles': {'q05': {'WHEAT': [26,
                                 26,
                                 27,
                                 27,
                                 27,
                                 27,
                                 28,
                                 28,
                                 28,
                                 28,
                                 28,
                                 28,
                                 29,
                                 30,
                                 31,
                                 32,
                                 33,
                                 33,
                                 34,
                                 35,
                                 36,
                                 36,
                                 37,
                                 38,
                                 38,
                                 39,
                                 40,
                                 40,
                                 41,
                                 42],
                       'CARROT': [35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37],
                       'TOMATO': [60,
                                  60,
                                  60,
                                  60,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  64],
                       'STRAWBERRY': [128,
                                      132,
                                      135,
                                      137,
                                      139,
                                      141,
                                      142,
                                      144,
                                      145,
                                      147,
                                      148,
                                      149,
                                      150,
                                      151,
                                      153,
                                      159,
                                      165,
                                      170,
                                      179,
                                      186,
                                      193,
                                      196,
                                      199,
                                      202,
                                      208,
                                      213,
                                      218,
                                      222,
                                      227,
                                      231],
                       'MELON': [256,
                                 260,
                                 262,
                                 264,
                                 266,
                                 267,
                                 268,
                                 269,
                                 270,
                                 271,
                                 272,
                                 272,
                                 273,
                                 274,
                                 274,
                                 275,
                                 275,
                                 276,
                                 276,
                                 277,
                                 277,
                                 277,
                                 278,
                                 278,
                                 279,
                                 279,
                                 279,
                                 280,
                                 280,
                                 280],
                       'EGG': [50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               52,
                               52,
                               52,
                               52,
                               52,
                               52],
                       'MILK': [169,
                                172,
                                175,
                                177,
                                179,
                                181,
                                183,
                                185,
                                186,
                                187,
                                189,
                                190,
                                191,
                                193,
                                194,
                                195,
                                196,
                                197,
                                198,
                                199,
                                200,
                                206,
                                211,
                                216,
                                221,
                                225,
                                229,
                                233,
                                236,
                                240],
                       'WOOL': [206,
                                209,
                                212,
                                214,
                                215,
                                217,
                                218,
                                219,
                                220,
                                221,
                                221,
                                222,
                                223,
                                223,
                                224,
                                224,
                                225,
                                225,
                                226,
                                226,
                                227,
                                227,
                                227,
                                228,
                                228,
                                228,
                                229,
                                229,
                                229,
                                229],
                       'FERTILIZER': [100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100]},
               'q10': {'WHEAT': [26,
                                 26,
                                 27,
                                 27,
                                 27,
                                 27,
                                 28,
                                 28,
                                 28,
                                 29,
                                 30,
                                 30,
                                 32,
                                 32,
                                 33,
                                 34,
                                 35,
                                 35,
                                 36,
                                 36,
                                 37,
                                 38,
                                 39,
                                 39,
                                 40,
                                 41,
                                 41,
                                 42,
                                 43,
                                 43],
                       'CARROT': [35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37,
                                  37],
                       'TOMATO': [60,
                                  60,
                                  60,
                                  60,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  62,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  63,
                                  64],
                       'STRAWBERRY': [128,
                                      132,
                                      135,
                                      137,
                                      139,
                                      141,
                                      142,
                                      144,
                                      145,
                                      147,
                                      148,
                                      149,
                                      157,
                                      163,
                                      168,
                                      177,
                                      185,
                                      191,
                                      195,
                                      198,
                                      201,
                                      206,
                                      212,
                                      217,
                                      223,
                                      230,
                                      235,
                                      239,
                                      243,
                                      247],
                       'MELON': [256,
                                 260,
                                 262,
                                 264,
                                 266,
                                 267,
                                 268,
                                 269,
                                 270,
                                 271,
                                 272,
                                 272,
                                 273,
                                 274,
                                 274,
                                 275,
                                 275,
                                 276,
                                 276,
                                 277,
                                 277,
                                 277,
                                 278,
                                 278,
                                 279,
                                 279,
                                 279,
                                 280,
                                 280,
                                 280],
                       'EGG': [50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               52,
                               52,
                               52,
                               52,
                               52,
                               52],
                       'MILK': [169,
                                172,
                                175,
                                177,
                                179,
                                181,
                                183,
                                185,
                                186,
                                187,
                                189,
                                190,
                                191,
                                193,
                                194,
                                201,
                                207,
                                212,
                                217,
                                221,
                                226,
                                230,
                                233,
                                237,
                                243,
                                249,
                                254,
                                257,
                                259,
                                262],
                       'WOOL': [206,
                                209,
                                212,
                                214,
                                215,
                                217,
                                218,
                                219,
                                220,
                                221,
                                221,
                                222,
                                223,
                                223,
                                224,
                                224,
                                225,
                                225,
                                226,
                                226,
                                227,
                                227,
                                227,
                                228,
                                228,
                                228,
                                229,
                                229,
                                229,
                                229],
                       'FERTILIZER': [100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100]},
               'q25': {'WHEAT': [26,
                                 26,
                                 27,
                                 27,
                                 27,
                                 27,
                                 29,
                                 29,
                                 30,
                                 31,
                                 32,
                                 33,
                                 34,
                                 34,
                                 34,
                                 35,
                                 36,
                                 37,
                                 38,
                                 38,
                                 39,
                                 40,
                                 41,
                                 42,
                                 42,
                                 43,
                                 44,
                                 44,
                                 45,
                                 46],
                       'CARROT': [35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  36,
                                  37,
                                  37,
                                  38,
                                  38,
                                  39,
                                  39,
                                  40,
                                  41,
                                  42,
                                  43,
                                  44,
                                  46,
                                  46,
                                  47,
                                  49],
                       'TOMATO': [60,
                                  60,
                                  60,
                                  60,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  62,
                                  62,
                                  62,
                                  63,
                                  63,
                                  64,
                                  65,
                                  66,
                                  67,
                                  68,
                                  69,
                                  69,
                                  70,
                                  71,
                                  72,
                                  73,
                                  75,
                                  77],
                       'STRAWBERRY': [128,
                                      132,
                                      135,
                                      137,
                                      139,
                                      141,
                                      142,
                                      144,
                                      145,
                                      154,
                                      160,
                                      166,
                                      175,
                                      183,
                                      190,
                                      196,
                                      202,
                                      207,
                                      212,
                                      217,
                                      222,
                                      228,
                                      234,
                                      240,
                                      245,
                                      251,
                                      256,
                                      261,
                                      265,
                                      270],
                       'MELON': [256,
                                 260,
                                 262,
                                 264,
                                 266,
                                 267,
                                 268,
                                 269,
                                 270,
                                 271,
                                 272,
                                 272,
                                 273,
                                 274,
                                 274,
                                 275,
                                 275,
                                 276,
                                 276,
                                 277,
                                 277,
                                 277,
                                 278,
                                 278,
                                 279,
                                 279,
                                 279,
                                 280,
                                 280,
                                 280],
                       'EGG': [50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               51,
                               52,
                               52,
                               53,
                               53,
                               53,
                               54,
                               54,
                               55,
                               55,
                               56,
                               56,
                               57,
                               58,
                               58],
                       'MILK': [169,
                                172,
                                175,
                                177,
                                179,
                                181,
                                183,
                                185,
                                186,
                                195,
                                202,
                                208,
                                213,
                                218,
                                222,
                                226,
                                230,
                                234,
                                240,
                                246,
                                252,
                                254,
                                257,
                                260,
                                267,
                                271,
                                274,
                                280,
                                286,
                                291],
                       'WOOL': [206,
                                209,
                                212,
                                214,
                                215,
                                217,
                                218,
                                219,
                                220,
                                221,
                                221,
                                222,
                                223,
                                223,
                                224,
                                224,
                                225,
                                225,
                                226,
                                226,
                                227,
                                227,
                                227,
                                228,
                                228,
                                228,
                                229,
                                229,
                                229,
                                229],
                       'FERTILIZER': [100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100]},
               'q50': {'WHEAT': [26,
                                 26,
                                 27,
                                 28,
                                 29,
                                 30,
                                 31,
                                 31,
                                 32,
                                 33,
                                 33,
                                 34,
                                 35,
                                 35,
                                 36,
                                 37,
                                 38,
                                 39,
                                 40,
                                 40,
                                 41,
                                 42,
                                 43,
                                 44,
                                 44,
                                 45,
                                 46,
                                 47,
                                 47,
                                 48],
                       'CARROT': [35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  36,
                                  36,
                                  36,
                                  37,
                                  38,
                                  39,
                                  39,
                                  40,
                                  40,
                                  41,
                                  42,
                                  43,
                                  44,
                                  44,
                                  45,
                                  47,
                                  49,
                                  51,
                                  52,
                                  53,
                                  54,
                                  56,
                                  57,
                                  58],
                       'TOMATO': [60,
                                  60,
                                  60,
                                  60,
                                  61,
                                  61,
                                  61,
                                  61,
                                  61,
                                  62,
                                  63,
                                  64,
                                  64,
                                  65,
                                  66,
                                  67,
                                  68,
                                  69,
                                  71,
                                  72,
                                  73,
                                  75,
                                  76,
                                  78,
                                  79,
                                  80,
                                  81,
                                  82,
                                  84,
                                  86],
                       'STRAWBERRY': [128,
                                      132,
                                      135,
                                      137,
                                      139,
                                      141,
                                      150,
                                      158,
                                      164,
                                      173,
                                      181,
                                      188,
                                      195,
                                      201,
                                      206,
                                      211,
                                      216,
                                      221,
                                      229,
                                      235,
                                      239,
                                      248,
                                      253,
                                      260,
                                      266,
                                      272,
                                      277,
                                      283,
                                      288,
                                      293],
                       'MELON': [256,
                                 260,
                                 262,
                                 264,
                                 266,
                                 267,
                                 268,
                                 269,
                                 270,
                                 271,
                                 272,
                                 272,
                                 273,
                                 274,
                                 274,
                                 275,
                                 275,
                                 276,
                                 276,
                                 277,
                                 277,
                                 277,
                                 278,
                                 278,
                                 279,
                                 279,
                                 279,
                                 280,
                                 280,
                                 280],
                       'EGG': [50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               51,
                               51,
                               51,
                               52,
                               52,
                               53,
                               53,
                               53,
                               54,
                               54,
                               55,
                               56,
                               57,
                               57,
                               58,
                               59,
                               59,
                               60,
                               60,
                               61,
                               62,
                               63],
                       'MILK': [169,
                                172,
                                175,
                                177,
                                179,
                                181,
                                191,
                                199,
                                205,
                                211,
                                216,
                                220,
                                228,
                                235,
                                241,
                                244,
                                247,
                                250,
                                258,
                                265,
                                272,
                                276,
                                280,
                                284,
                                292,
                                297,
                                300,
                                305,
                                310,
                                315],
                       'WOOL': [206,
                                209,
                                212,
                                214,
                                215,
                                217,
                                218,
                                219,
                                220,
                                221,
                                221,
                                222,
                                223,
                                223,
                                224,
                                224,
                                225,
                                225,
                                230,
                                233,
                                235,
                                237,
                                238,
                                239,
                                241,
                                243,
                                244,
                                245,
                                245,
                                246],
                       'FERTILIZER': [100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100]},
               'q75': {'WHEAT': [26,
                                 26,
                                 27,
                                 28,
                                 29,
                                 30,
                                 31,
                                 32,
                                 33,
                                 34,
                                 34,
                                 35,
                                 36,
                                 37,
                                 38,
                                 39,
                                 39,
                                 40,
                                 41,
                                 42,
                                 43,
                                 44,
                                 45,
                                 45,
                                 46,
                                 47,
                                 48,
                                 49,
                                 49,
                                 50],
                       'CARROT': [35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  35,
                                  36,
                                  37,
                                  38,
                                  40,
                                  41,
                                  42,
                                  43,
                                  44,
                                  45,
                                  46,
                                  48,
                                  49,
                                  50,
                                  52,
                                  53,
                                  55,
                                  57,
                                  59,
                                  61,
                                  63,
                                  65,
                                  67,
                                  69,
                                  71],
                       'TOMATO': [60,
                                  60,
                                  60,
                                  60,
                                  61,
                                  61,
                                  62,
                                  62,
                                  63,
                                  65,
                                  66,
                                  68,
                                  69,
                                  70,
                                  70,
                                  72,
                                  74,
                                  75,
                                  77,
                                  78,
                                  80,
                                  81,
                                  83,
                                  85,
                                  92,
                                  101,
                                  109,
                                  124,
                                  143,
                                  165],
                       'STRAWBERRY': [128,
                                      132,
                                      135,
                                      147,
                                      155,
                                      161,
                                      167,
                                      172,
                                      176,
                                      184,
                                      191,
                                      197,
                                      205,
                                      213,
                                      220,
                                      226,
                                      232,
                                      238,
                                      245,
                                      252,
                                      259,
                                      265,
                                      271,
                                      277,
                                      284,
                                      290,
                                      296,
                                      302,
                                      308,
                                      314],
                       'MELON': [256,
                                 260,
                                 262,
                                 264,
                                 266,
                                 267,
                                 268,
                                 269,
                                 270,
                                 271,
                                 272,
                                 272,
                                 273,
                                 274,
                                 274,
                                 275,
                                 275,
                                 276,
                                 276,
                                 277,
                                 277,
                                 277,
                                 278,
                                 278,
                                 279,
                                 279,
                                 279,
                                 280,
                                 280,
                                 280],
                       'EGG': [50,
                               50,
                               50,
                               50,
                               50,
                               50,
                               51,
                               51,
                               52,
                               52,
                               53,
                               54,
                               54,
                               55,
                               55,
                               56,
                               57,
                               58,
                               58,
                               59,
                               60,
                               61,
                               62,
                               62,
                               64,
                               65,
                               66,
                               67,
                               68,
                               69],
                       'MILK': [169,
                                172,
                                175,
                                187,
                                196,
                                203,
                                208,
                                214,
                                218,
                                223,
                                227,
                                231,
                                240,
                                249,
                                256,
                                261,
                                266,
                                271,
                                277,
                                283,
                                289,
                                294,
                                299,
                                304,
                                312,
                                318,
                                323,
                                329,
                                334,
                                339],
                       'WOOL': [206,
                                209,
                                212,
                                214,
                                215,
                                217,
                                218,
                                219,
                                220,
                                227,
                                231,
                                233,
                                235,
                                237,
                                238,
                                241,
                                242,
                                244,
                                244,
                                245,
                                246,
                                246,
                                247,
                                247,
                                247,
                                248,
                                248,
                                249,
                                250,
                                250],
                       'FERTILIZER': [100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100]},
               'q90': {'WHEAT': [26,
                                 26,
                                 27,
                                 28,
                                 29,
                                 30,
                                 31,
                                 32,
                                 33,
                                 34,
                                 35,
                                 36,
                                 37,
                                 38,
                                 39,
                                 40,
                                 41,
                                 41,
                                 42,
                                 43,
                                 44,
                                 45,
                                 46,
                                 47,
                                 48,
                                 48,
                                 49,
                                 50,
                                 51,
                                 52],
                       'CARROT': [35,
                                  35,
                                  35,
                                  36,
                                  37,
                                  38,
                                  39,
                                  40,
                                  41,
                                  42,
                                  43,
                                  44,
                                  46,
                                  47,
                                  49,
                                  51,
                                  53,
                                  55,
                                  57,
                                  58,
                                  60,
                                  63,
                                  65,
                                  68,
                                  70,
                                  74,
                                  80,
                                  92,
                                  104,
                                  125],
                       'TOMATO': [60,
                                  60,
                                  60,
                                  61,
                                  62,
                                  63,
                                  64,
                                  65,
                                  65,
                                  67,
                                  69,
                                  70,
                                  72,
                                  73,
                                  75,
                                  76,
                                  78,
                                  79,
                                  82,
                                  84,
                                  88,
                                  95,
                                  106,
                                  121,
                                  139,
                                  160,
                                  185,
                                  233,
                                  278,
                                  317],
                       'STRAWBERRY': [128,
                                      132,
                                      135,
                                      147,
                                      155,
                                      161,
                                      171,
                                      179,
                                      187,
                                      196,
                                      204,
                                      212,
                                      219,
                                      226,
                                      232,
                                      238,
                                      243,
                                      248,
                                      257,
                                      265,
                                      272,
                                      279,
                                      286,
                                      292,
                                      298,
                                      304,
                                      310,
                                      317,
                                      324,
                                      330],
                       'MELON': [256,
                                 260,
                                 262,
                                 264,
                                 266,
                                 267,
                                 268,
                                 269,
                                 270,
                                 271,
                                 272,
                                 272,
                                 273,
                                 274,
                                 274,
                                 275,
                                 275,
                                 276,
                                 276,
                                 277,
                                 277,
                                 277,
                                 278,
                                 278,
                                 279,
                                 279,
                                 279,
                                 280,
                                 280,
                                 280],
                       'EGG': [50,
                               50,
                               50,
                               51,
                               51,
                               51,
                               52,
                               52,
                               53,
                               53,
                               54,
                               55,
                               56,
                               57,
                               57,
                               58,
                               59,
                               60,
                               61,
                               62,
                               63,
                               64,
                               65,
                               67,
                               68,
                               69,
                               70,
                               73,
                               78,
                               83],
                       'MILK': [169,
                                172,
                                175,
                                187,
                                196,
                                203,
                                213,
                                221,
                                229,
                                236,
                                242,
                                248,
                                253,
                                258,
                                263,
                                270,
                                276,
                                282,
                                292,
                                299,
                                304,
                                310,
                                316,
                                322,
                                329,
                                336,
                                343,
                                348,
                                353,
                                357],
                       'WOOL': [206,
                                209,
                                212,
                                224,
                                229,
                                232,
                                235,
                                236,
                                238,
                                239,
                                240,
                                241,
                                242,
                                243,
                                244,
                                244,
                                245,
                                245,
                                246,
                                247,
                                248,
                                249,
                                250,
                                250,
                                251,
                                251,
                                252,
                                252,
                                253,
                                253],
                       'FERTILIZER': [100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100]},
               'q95': {'WHEAT': [26,
                                 26,
                                 27,
                                 28,
                                 29,
                                 30,
                                 31,
                                 32,
                                 33,
                                 34,
                                 35,
                                 36,
                                 37,
                                 38,
                                 39,
                                 40,
                                 41,
                                 42,
                                 43,
                                 44,
                                 45,
                                 46,
                                 47,
                                 48,
                                 49,
                                 49,
                                 50,
                                 51,
                                 52,
                                 53],
                       'CARROT': [35,
                                  35,
                                  35,
                                  36,
                                  37,
                                  38,
                                  39,
                                  40,
                                  41,
                                  43,
                                  44,
                                  46,
                                  48,
                                  50,
                                  52,
                                  54,
                                  55,
                                  59,
                                  61,
                                  63,
                                  65,
                                  68,
                                  70,
                                  76,
                                  83,
                                  98,
                                  114,
                                  135,
                                  159,
                                  187],
                       'TOMATO': [60,
                                  60,
                                  60,
                                  61,
                                  62,
                                  63,
                                  64,
                                  66,
                                  68,
                                  69,
                                  71,
                                  72,
                                  74,
                                  75,
                                  77,
                                  78,
                                  81,
                                  84,
                                  87,
                                  95,
                                  105,
                                  119,
                                  137,
                                  158,
                                  191,
                                  229,
                                  274,
                                  325,
                                  382,
                                  445],
                       'STRAWBERRY': [128,
                                      132,
                                      135,
                                      147,
                                      155,
                                      161,
                                      171,
                                      179,
                                      187,
                                      196,
                                      204,
                                      212,
                                      221,
                                      230,
                                      237,
                                      245,
                                      251,
                                      258,
                                      264,
                                      270,
                                      276,
                                      284,
                                      292,
                                      299,
                                      307,
                                      313,
                                      320,
                                      326,
                                      333,
                                      339],
                       'MELON': [256,
                                 260,
                                 262,
                                 264,
                                 266,
                                 267,
                                 268,
                                 269,
                                 270,
                                 271,
                                 272,
                                 272,
                                 273,
                                 274,
                                 274,
                                 275,
                                 275,
                                 276,
                                 276,
                                 277,
                                 277,
                                 277,
                                 278,
                                 278,
                                 279,
                                 279,
                                 279,
                                 280,
                                 280,
                                 280],
                       'EGG': [50,
                               50,
                               50,
                               51,
                               51,
                               51,
                               52,
                               53,
                               54,
                               55,
                               55,
                               56,
                               57,
                               58,
                               58,
                               59,
                               60,
                               62,
                               63,
                               64,
                               65,
                               67,
                               68,
                               69,
                               70,
                               73,
                               78,
                               84,
                               92,
                               102],
                       'MILK': [169,
                                172,
                                175,
                                187,
                                196,
                                203,
                                213,
                                221,
                                229,
                                239,
                                247,
                                255,
                                262,
                                269,
                                276,
                                282,
                                287,
                                293,
                                300,
                                306,
                                313,
                                319,
                                325,
                                330,
                                338,
                                345,
                                350,
                                357,
                                363,
                                368],
                       'WOOL': [206,
                                209,
                                212,
                                224,
                                229,
                                232,
                                235,
                                236,
                                238,
                                239,
                                240,
                                241,
                                243,
                                244,
                                245,
                                246,
                                247,
                                248,
                                249,
                                250,
                                250,
                                251,
                                251,
                                252,
                                253,
                                253,
                                254,
                                254,
                                255,
                                255],
                       'FERTILIZER': [100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100,
                                      100]}},
 'grid': {'WHEAT': [1, 6, 12, 19, 25, 31, 38, 50, 75, 100, 150, 200, 250, 300],
          'CARROT': [9, 18, 25, 26, 35, 44, 50, 52, 70, 100, 105, 140, 150, 200, 210, 250, 300],
          'TOMATO': [15,
                     25,
                     30,
                     45,
                     50,
                     60,
                     75,
                     90,
                     100,
                     120,
                     150,
                     180,
                     200,
                     240,
                     250,
                     300,
                     360],
          'STRAWBERRY': [1,
                         25,
                         30,
                         50,
                         60,
                         90,
                         100,
                         120,
                         150,
                         180,
                         200,
                         240,
                         250,
                         300,
                         360,
                         480,
                         720],
          'MELON': [1,
                    25,
                    50,
                    62,
                    100,
                    125,
                    150,
                    188,
                    200,
                    250,
                    300,
                    312,
                    375,
                    500,
                    750,
                    1000,
                    1500],
          'EGG': [1, 12, 25, 38, 50, 62, 75, 100, 150, 200, 250, 300],
          'MILK': [1,
                   25,
                   40,
                   50,
                   80,
                   100,
                   120,
                   150,
                   160,
                   200,
                   240,
                   250,
                   300,
                   320,
                   480,
                   640,
                   960],
          'WOOL': [1, 25, 50, 100, 150, 200, 250, 300, 400, 600, 800, 1200],
          'FERTILIZER': [1, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 600]},
 'tail_prob': {'WHEAT': [[1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.3906,
                          0.625,
                          0.625,
                          0.7715,
                          0.8594,
                          0.9143,
                          0.9473,
                          0.9473,
                          0.9679,
                          0.9802,
                          0.9802,
                          0.9926,
                          0.9926,
                          0.9926,
                          0.9972,
                          0.9972,
                          0.9972,
                          0.999,
                          0.999,
                          0.9996,
                          0.9996,
                          0.9996,
                          0.9996],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.1526,
                          0.3014,
                          0.3929,
                          0.5188,
                          0.651,
                          0.7188,
                          0.8329,
                          0.8683,
                          0.9015,
                          0.9327,
                          0.9478,
                          0.9613,
                          0.9741,
                          0.981,
                          0.9835,
                          0.9885],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0373,
                          0.0736,
                          0.1406,
                          0.2155],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0]],
               'CARROT': [[1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [0.0,
                           0.0,
                           0.0,
                           0.25,
                           0.25,
                           0.25,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0195,
                           0.0469,
                           0.0723,
                           0.1636,
                           0.2046,
                           0.3057,
                           0.3276,
                           0.3716,
                           0.4397,
                           0.4611,
                           0.499,
                           0.5798,
                           0.6076,
                           0.6471,
                           0.6848,
                           0.7057,
                           0.7353,
                           0.7636,
                           0.7914,
                           0.8137,
                           0.8137],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0039,
                           0.02,
                           0.0415,
                           0.0579,
                           0.1046,
                           0.1381,
                           0.1671,
                           0.2499,
                           0.3066,
                           0.3795,
                           0.3993,
                           0.4417,
                           0.5013,
                           0.5208,
                           0.5595,
                           0.6065,
                           0.6297,
                           0.6431,
                           0.6797],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.002,
                           0.0059,
                           0.0217,
                           0.043,
                           0.0674,
                           0.1061,
                           0.1392,
                           0.1751,
                           0.2213,
                           0.2844,
                           0.3364,
                           0.3917,
                           0.4169,
                           0.4652,
                           0.5118,
                           0.5344,
                           0.5815,
                           0.6186,
                           0.6431],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0003,
                           0.0012,
                           0.0046,
                           0.0098,
                           0.0168,
                           0.0304,
                           0.0489,
                           0.0787,
                           0.097,
                           0.1266,
                           0.1634,
                           0.1851,
                           0.2217,
                           0.2606],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0001,
                           0.0007,
                           0.0023,
                           0.0058,
                           0.0111,
                           0.0185,
                           0.0302,
                           0.0437,
                           0.0602,
                           0.0848,
                           0.1091,
                           0.1262],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0001,
                           0.0005,
                           0.0018,
                           0.0049,
                           0.0094,
                           0.0152,
                           0.0268,
                           0.04,
                           0.0602,
                           0.0785,
                           0.099,
                           0.1262],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0001,
                           0.0005,
                           0.0013,
                           0.0032,
                           0.0071,
                           0.012,
                           0.0212,
                           0.0318,
                           0.0455,
                           0.0603,
                           0.0781],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0004,
                           0.0009,
                           0.0026,
                           0.0059,
                           0.0104,
                           0.0177,
                           0.0275,
                           0.0394,
                           0.0565,
                           0.0701],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0002,
                           0.0008,
                           0.0018,
                           0.0043,
                           0.0083,
                           0.0131,
                           0.0214,
                           0.0323,
                           0.0464],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0002,
                           0.0006,
                           0.0018,
                           0.0036,
                           0.0071,
                           0.0131,
                           0.02,
                           0.0296,
                           0.0412],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0002,
                           0.0007,
                           0.0019,
                           0.004,
                           0.0067,
                           0.0125,
                           0.0203,
                           0.0307],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0001,
                           0.0003,
                           0.0009,
                           0.002,
                           0.0043,
                           0.0079,
                           0.0129,
                           0.019]],
               'TOMATO': [[1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [0.0,
                           0.0,
                           0.0,
                           0.25,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0,
                           1.0],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0156,
                           0.0273,
                           0.0742,
                           0.1211,
                           0.1914,
                           0.2002,
                           0.2617,
                           0.3342,
                           0.3408,
                           0.4562,
                           0.5056,
                           0.5847,
                           0.5921,
                           0.6292,
                           0.6885,
                           0.7108,
                           0.7442,
                           0.7553],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0068,
                           0.0186,
                           0.031,
                           0.0552,
                           0.0793,
                           0.1216,
                           0.1678,
                           0.1958,
                           0.2535,
                           0.3017,
                           0.3264,
                           0.3808,
                           0.4401,
                           0.492],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.001,
                           0.0068,
                           0.0186,
                           0.0376,
                           0.0552,
                           0.0799,
                           0.1134,
                           0.153,
                           0.1962,
                           0.2535,
                           0.2794,
                           0.3276,
                           0.3808,
                           0.3956],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.001,
                           0.0068,
                           0.0127,
                           0.0244,
                           0.0453,
                           0.0651,
                           0.1134,
                           0.1418,
                           0.1851,
                           0.2312,
                           0.2572,
                           0.3042,
                           0.3474],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.001,
                           0.0046,
                           0.0127,
                           0.0244,
                           0.0387,
                           0.0651,
                           0.0887,
                           0.1233,
                           0.1517,
                           0.1917,
                           0.2238,
                           0.2597],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0017,
                           0.0046,
                           0.0127,
                           0.0211,
                           0.0464,
                           0.0652,
                           0.0887,
                           0.1241,
                           0.1517,
                           0.1806,
                           0.2238],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.001,
                           0.0046,
                           0.0078,
                           0.0145,
                           0.0338,
                           0.0465,
                           0.0759,
                           0.0998,
                           0.1245,
                           0.1583,
                           0.1867],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.001,
                           0.0046,
                           0.0094,
                           0.0145,
                           0.03,
                           0.0453,
                           0.0776,
                           0.0998,
                           0.1245,
                           0.1583],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.001,
                           0.003,
                           0.0078,
                           0.0145,
                           0.0239,
                           0.0428,
                           0.0598,
                           0.0887,
                           0.1097,
                           0.1336],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.001,
                           0.0032,
                           0.0096,
                           0.0149,
                           0.0241,
                           0.0454,
                           0.0598,
                           0.0887,
                           0.1097],
                          [0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0,
                           0.0002,
                           0.0012,
                           0.0032,
                           0.0083,
                           0.0174,
                           0.0241,
                           0.0417,
                           0.0578,
                           0.0714]],
               'STRAWBERRY': [[1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.5,
                               0.5,
                               0.5,
                               0.75,
                               0.75,
                               0.875,
                               0.875,
                               0.875,
                               0.9375,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.25,
                               0.5,
                               0.625,
                               0.625,
                               0.75,
                               0.8125,
                               0.8125,
                               0.875,
                               0.9062,
                               0.9375,
                               0.9375,
                               0.9531,
                               0.9688,
                               0.9766,
                               0.9844,
                               0.9844,
                               0.9883,
                               0.9922,
                               0.9922,
                               0.9961,
                               0.9961,
                               0.9961],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.125,
                               0.25,
                               0.375,
                               0.5625,
                               0.5625,
                               0.6875,
                               0.7812,
                               0.7812,
                               0.8438,
                               0.8906,
                               0.9219,
                               0.9297,
                               0.9453,
                               0.9609,
                               0.9648,
                               0.9766,
                               0.9805,
                               0.9844,
                               0.9883,
                               0.9883],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0625,
                               0.1562,
                               0.2188,
                               0.3125,
                               0.4375,
                               0.5,
                               0.6016,
                               0.6719,
                               0.7109,
                               0.7773,
                               0.8398,
                               0.875,
                               0.8867,
                               0.9102,
                               0.9258],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0625,
                               0.0938,
                               0.1719,
                               0.2812,
                               0.3438,
                               0.4609,
                               0.5391,
                               0.5938,
                               0.6797,
                               0.7578,
                               0.8086,
                               0.832,
                               0.8633,
                               0.8867],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0156,
                               0.0391,
                               0.082,
                               0.1445,
                               0.1914,
                               0.2734,
                               0.3477,
                               0.4336],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0039],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0]],
               'MELON': [[1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0,
                          1.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0],
                         [0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0,
                          0.0]],
               'EGG': [[1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0],
                       [1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0],
                       [1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0],
                       [1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0],
                       [0.0,
                        0.0,
                        0.0,
                        0.25,
                        0.25,
                        0.25,
                        0.4375,
                        0.4375,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                        1.0],
                       [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0039,
                        0.0186,
                        0.0303,
                        0.0508,
                        0.0793,
                        0.1211,
                        0.1678,
                        0.2255,
                        0.2469,
                        0.3017,
                        0.3598,
                        0.3795,
                        0.4401,
                        0.492,
                        0.5291],
                       [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.001,
                        0.0019,
                        0.0078,
                        0.0145,
                        0.0239,
                        0.0428,
                        0.0598,
                        0.0788,
                        0.1097,
                        0.1336],
                       [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0002,
                        0.0012,
                        0.0032,
                        0.0088,
                        0.0177,
                        0.0243,
                        0.0355,
                        0.0578],
                       [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0001,
                        0.0007,
                        0.0024,
                        0.0042,
                        0.0079,
                        0.0155],
                       [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0001,
                        0.0003,
                        0.0008,
                        0.002,
                        0.0042],
                       [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0001,
                        0.0005,
                        0.0012],
                       [0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0001,
                        0.0005]],
               'MILK': [[1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.375,
                         0.375,
                         0.375,
                         0.6094,
                         0.6094,
                         0.7559,
                         0.7559,
                         0.7559,
                         0.8474,
                         0.8474,
                         0.9046,
                         0.9046,
                         0.9046,
                         0.9404,
                         0.9404,
                         0.9404,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.1406,
                         0.1406,
                         0.2285,
                         0.3713,
                         0.5178,
                         0.5384,
                         0.6071,
                         0.6986,
                         0.7115,
                         0.7902,
                         0.8116,
                         0.8465,
                         0.8689,
                         0.8823,
                         0.9041,
                         0.9264,
                         0.9264,
                         0.9488,
                         0.9488,
                         0.9488],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0527,
                         0.1406,
                         0.2285,
                         0.2615,
                         0.3713,
                         0.4606,
                         0.4812,
                         0.62,
                         0.6758,
                         0.7544,
                         0.7625,
                         0.7973,
                         0.8465,
                         0.8683,
                         0.8873,
                         0.9041,
                         0.9125,
                         0.9264,
                         0.9348],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0198,
                         0.0368,
                         0.0852,
                         0.1259,
                         0.197,
                         0.2462,
                         0.2977,
                         0.3826,
                         0.4398,
                         0.4851,
                         0.5773,
                         0.6222,
                         0.6705],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0074,
                         0.0244,
                         0.0385,
                         0.0673,
                         0.1236,
                         0.1687,
                         0.2312,
                         0.2831,
                         0.3297,
                         0.3929,
                         0.4382],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0]],
               'WOOL': [[1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0,
                         1.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0002,
                         0.002,
                         0.0039,
                         0.0071,
                         0.0205,
                         0.025,
                         0.0383,
                         0.0605,
                         0.0656,
                         0.0864,
                         0.1141,
                         0.1403,
                         0.1445,
                         0.1755,
                         0.1986,
                         0.1996],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0],
                        [0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0,
                         0.0]],
               'FERTILIZER': [[1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0,
                               1.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0],
                              [0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0,
                               0.0]]}}

# ===========================================================================
# END MODULE: strategy/baked_price_table.py
# ===========================================================================

"""Pure-python price math mirroring the engine exactly (no numpy)."""





def _shape(func, x, T):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "log10":
        return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + 8.0 * max(0.0, u - 1.0) ** 2
    return x


def amplitude(item, side):
    p = MARKET_PARAMS[item]
    f = p["bf"] if side == "below" else p["af"]
    target = p["bt"] if side == "below" else p["at"]
    return target * p["base"] / _shape(f, p["T"], p["T"])


def market_price(item, inventory):
    """Engine-exact sell quote."""
    p = MARKET_PARAMS[item]
    base, I0, T = p["base"], MARKET_I0, p["T"]
    inv = float(inventory)
    if inv < I0:
        f = p["bf"]
        amp = p["bt"] * base / _shape(f, T, T)
        price = base + amp * _shape(f, I0 - inv, T)
    else:
        f = p["af"]
        amp = p["at"] * base / _shape(f, T, T)
        price = base - amp * _shape(f, inv - I0, T)
    return max(PRICE_FLOOR, int(round(price)))


def _solve_shape(func, y, T):
    """Solve _shape(func, x) == y for x >= 0 (y >= 0)."""
    if func == "linear":
        return y
    if func == "sq":
        return math.sqrt(y)
    if func == "sqrt":
        return y * y
    if func == "log":
        return math.expm1(y)
    if func == "log10":
        return 10.0 ** y - 1.0
    if func == "hinge":
        if y <= 1.0:
            return y * T
        u = (15.0 + math.sqrt(32.0 * y - 31.0)) / 16.0
        return u * T
    raise ValueError(func)


def inventory_for_price_at_least(item, min_price):
    """Max units that can be ADDED above I0 while the quote stays >= min_price.

    Returns the glut-side crossing inventory; (level - I0) is the dump budget.
    """
    p = MARKET_PARAMS[item]
    target = max(float(min_price), PRICE_FLOOR + 1)  # strictly above floor
    if target >= p["base"]:
        return float(MARKET_I0)
    y = (p["base"] - target) / amplitude(item, "above")
    return MARKET_I0 + _solve_shape(p["af"], y, p["T"])


def inventory_at_price(item, target_price):
    """Exact continuous inverse of market_price (both branches).

    Scarcity targets (< base) return inventory BELOW I0; glut targets
    (> base) return inventory ABOVE I0; base returns I0. Targets below the
    $1 floor are clamped to the floor crossing. Used to convert a forecast
    price path into the implied underlying inventory path.
    """
    p = MARKET_PARAMS[item]
    base = p["base"]
    target = max(float(target_price), PRICE_FLOOR)
    if abs(target - base) < 1e-12:
        return float(MARKET_I0)
    if target > base:
        y = (target - base) / amplitude(item, "below")
        return float(MARKET_I0 - _solve_shape(p["bf"], y, p["T"]))
    y = (base - target) / amplitude(item, "above")
    return float(MARKET_I0 + _solve_shape(p["af"], y, p["T"]))


def drip_batch_size(item, current_inventory, keep_frac):
    """Largest Q whose LAST unit still quotes >= keep_frac * spot.

    Uses a coarse-to-fine search on the continuous inverse; cheap and exact
    enough for slicing decisions.
    """
    spot = market_price(item, current_inventory)
    threshold = max(2, int(spot * keep_frac))
    limit = inventory_for_price_at_least(item, threshold)
    budget = int(limit - current_inventory)
    return max(0, budget), spot


def total_revenue_estimate(item, start_inventory, quantity):
    """TR of dumping `quantity` units one-at-a-time from start_inventory.

    Respects the $1-floor freeze: units sold at $1 don't shift inventory.
    """
    inv = float(start_inventory)
    total = 0
    for _ in range(int(quantity)):
        px = market_price(item, inv)
        total += px
        if px > PRICE_FLOOR:
            inv += 1.0
    return total


def optimal_dump_quantity(item, start_inventory, min_acceptable):
    """Q* before the marginal quote drops below min_acceptable."""
    inv = float(start_inventory)
    q = 0
    while True:
        px = market_price(item, inv)
        if px < min_acceptable:
            return q
        q += 1
        if px > PRICE_FLOOR:
            inv += 1.0
        else:  # at floor the quote never recovers by adding more
            return q

# ===========================================================================
# END MODULE: market/price_math.py
# ===========================================================================

"""Robust parsing of the Kaggle observation into typed structures.

Handles both plain dicts and kaggle Struct objects via the `g()` accessor.
"""



def g(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class TileView:
    __slots__ = ("x", "y", "raw", "kind", "crop", "planted_day", "watered_today",
                 "consecutive_unwatered", "yield_units", "fertilized_until_day",
                 "animal", "fed_today", "cared_today", "consecutive_unfed",
                 "fertilizer_available", "pending_care_bonus", "placed_day")

    def __init__(self, x, y, raw):
        self.x = x
        self.y = y
        self.raw = raw
        if raw is None:
            self.kind = "EMPTY"
        elif raw == "LOCKED":
            self.kind = "LOCKED"
        else:
            self.kind = g(raw, "kind", "?")
        self.crop = g(raw, "crop")
        self.planted_day = g(raw, "planted_day")
        self.watered_today = bool(g(raw, "watered_today", False))
        self.consecutive_unwatered = int(g(raw, "consecutive_unwatered", 0))
        self.yield_units = int(g(raw, "yield_units", 0) or 0)
        self.fertilized_until_day = int(g(raw, "fertilized_until_day", -1) or -1)
        self.animal = g(raw, "animal")
        self.fed_today = bool(g(raw, "fed_today", False))
        self.cared_today = bool(g(raw, "cared_today", False))
        self.consecutive_unfed = int(g(raw, "consecutive_unfed", 0))
        self.fertilizer_available = bool(g(raw, "fertilizer_available", False))
        self.pending_care_bonus = int(g(raw, "pending_care_bonus", 0) or 0)
        self.placed_day = g(raw, "placed_day")

    @property
    def is_plant(self):
        return self.kind == "PLANT"

    @property
    def is_animal(self):
        return self.animal is not None

    @property
    def pos(self):
        return (self.x, self.y)


class FarmView:
    """Public farm state for any player."""

    def __init__(self, raw):
        self.money = float(g(raw, "money", 0))
        self.tiles_raw = g(raw, "tiles", []) or []
        self.farmer = tuple(g(raw, "farmer", (4, 4)))
        self.hands = [tuple(h) for h in (g(raw, "hands", []) or [])]
        self.unlocked = set(g(raw, "unlocked_quadrants", ["NW"]) or ["NW"])
        self.hires_today = int(g(raw, "hires_today", 0))
        self.tiles = []
        for y, row in enumerate(self.tiles_raw):
            trow = []
            for x, t in enumerate(row):
                trow.append(TileView(x, y, t))
            self.tiles.append(trow)

    def tile_at(self, pos):
        x, y = pos
        if 0 <= y < len(self.tiles) and 0 <= x < len(self.tiles[0]):
            return self.tiles[y][x]
        return None

    def iter_tiles(self):
        for row in self.tiles:
            for t in row:
                yield t

    def quadrant_of(self, pos):
        x, y = pos
        half = len(self.tiles_raw[0]) // 2 if self.tiles_raw and self.tiles_raw[0] else 5
        return ("N" if y < half else "S") + ("W" if x < half else "E")

    def count_kind(self, kind):
        return sum(1 for t in self.iter_tiles() if t.kind == kind)


class MarketView:
    def __init__(self, raw):
        self.inventory = {k: float(v) for k, v in
                          (g(raw, "inventory", {}) or {}).items()}
        self.prices = {k: int(v) for k, v in
                       (g(raw, "prices", {}) or {}).items()}


class TownView:
    def __init__(self, raw):
        self.unlocked_shops = list(g(raw, "unlocked_shops", []) or [])


class PrivateView:
    def __init__(self, raw):
        self.shed = {k: int(v) for k, v in (g(raw, "shed", {}) or {}).items()
                     if int(v) > 0}
        self.seeds = {k: int(v) for k, v in (g(raw, "seeds", {}) or {}).items()
                      if int(v) > 0}
        invs = g(raw, "inventories", []) or []
        self.inventories = [{k: int(v) for k, v in (inv or {}).items() if int(v) > 0}
                            for inv in invs]

    def shed_count(self):
        return sum(self.shed.values())

    def unit_holding(self, idx):
        if idx < len(self.inventories):
            return self.inventories[idx]
        return {}


def parse_observation(obs):
    """Full observation parse into a light context object."""
    farms = g(obs, "farms", None)
    if not farms:
        return None
    player = int(g(obs, "player", 0))
    ctx = {
        "player": player,
        "day": int(g(obs, "day", 0)),
        "hour": int(g(obs, "hour", 0)),
        "step": int(g(obs, "day", 0)) * TURNS_PER_DAY + int(g(obs, "hour", 0)),
        "farm": FarmView(farms[player]),
        "market": MarketView(g(obs, "market")),
        "town": TownView(g(obs, "town")),
        "private": PrivateView(g(obs, "private")),
        "opponent_farm": FarmView(farms[1 - player]) if len(farms) > 1 else None,
        "n_units": 1 + len(FarmView(farms[player]).hands),
    }
    ctx["is_shed_adjacent"] = lambda pos: pos in SHED_ACCESS_TILES
    return ctx


# ---- derived per-tile attributes -------------------------------------------

def crop_age(tile, day):
    return day - tile.planted_day if tile.planted_day is not None else 0


def in_bonus_window(tile, day):
    cd = CROPS.get(tile.crop)
    if cd is None:
        return False
    age = crop_age(tile, day)
    start = cd.get("window_start", (cd["max_yield_day"] + 1) // 2)
    return start <= age <= cd["max_yield_day"]


def needs_water_today(tile, day):
    """Determine if a plant tile must/should be watered today under Points 1.2 & 1.5.
    
    Guardrail 1: Planting day ALWAYS requires same-day water (starts with counter=1).
    Guardrail 2: If missed yesterday (counter >= 1), MUST water today (prevent weed).
    Guardrail 3: In bonus window (one-time) or active production (ongoing) -> ALWAYS water.
    Guardrail 4: Pre-bonus / non-bonus -> alternate days by spatial checkerboard ((x + y + day) % 2 == 0).
    """
    if not tile.is_plant:
        return False
    if tile.watered_today:
        return False
        
    # Guardrail 1: Planting day
    if tile.planted_day is not None and tile.planted_day == day:
        return True
        
    # Guardrail 2: Missed yesterday -> mandatory survival watering
    if tile.consecutive_unwatered >= 1:
        return True
        
    cd = CROPS.get(tile.crop)
    if cd is None:
        return True
        
    # Guardrail 3: Ongoing crops (Tomato, Strawberry)
    if cd["ongoing"]:
        age = crop_age(tile, day)
        first_yield = cd.get("first_yield_day", 8)
        # In juvenile growth phase (no fruit yet) -> alternate days safely
        if age < first_yield:
            return (tile.x + tile.y + day) % 2 == 0
        # In production phase:
        # - Tomato: yields daily (ages 8-11) -> water daily
        # - Strawberry: yields on even ages (10, 12, 14, 16) -> water on production days
        interval = cd.get("interval", 1)
        if interval <= 1:
            return True
        is_production_day = (age - first_yield) % interval == 0
        if is_production_day:
            return True
        # Off-day during production -> alternate days
        return (tile.x + tile.y + day) % 2 == 0

    if in_bonus_window(tile, day):
        return True
        
    # Guardrail 4: Outside bonus window and watered yesterday -> alternate days
    return (tile.x + tile.y + day) % 2 == 0


def decay_step_for(tile):
    """First global step at which this one-time plant starts losing units."""
    cd = CROPS[tile.crop]
    if cd["ongoing"]:
        return None
    return (tile.planted_day + cd["max_yield_day"] + 1) * TURNS_PER_DAY


def turns_until_decay(tile, step):
    ds = decay_step_for(tile)
    return None if ds is None else max(0, ds - step)


def animal_production_days(tile):
    a = ANIMAL_LIST and None  # placeholder to keep lints quiet
    info = ANIMALS.get(tile.animal)
    if info is None:
        return set()
    first = tile.placed_day + info["first_yield_day"]
    return set(range(first, 31, info["interval"]))

# ===========================================================================
# END MODULE: state/observation_parser.py
# ===========================================================================

"""Persistent cross-turn memory: episode detection, drain ledger, deadlines."""




OPP_MONEY_WINDOW = 24  # sliding window of opponent money deltas (turns)

# Module-level (survives across turns within one process/episode).
_STATE = {
    "episode": None,
    "prev_inventory": None,
    "prev_shed": None,
    "known_shops": [],
    "town_drain_seen": {},       # product -> units inferred drained by town
    "opp_sales_inferred": {},    # product -> units inferred sold by opponent
    "our_units_sold": {},        # product -> units we sold (from our orders)
    "prev_opp_money": None,      # opponent money on previous turn
    "opp_money_deltas": deque(maxlen=OPP_MONEY_WINDOW),  # recent delta list
    "noop_attempts": 0,
    "invalid_guard": 0,
    "days_seen": set(),
}


def get_state(obs):
    """Parse + update persistent state. Returns (ctx, memory)."""
    mem = _STATE
    ctx = parse_observation(obs)
    if ctx is None:
        return None, mem

    marker = (ctx["day"], id(ctx))
    # New-episode detection: day went backwards or we saw a future day reset.
    reset_this_turn = False
    if mem["episode"] is not None and ctx["day"] < mem["episode"].get("last_day", 0):
        log("new episode detected; resetting memory")
        reset_memory(mem)
        reset_this_turn = True

    if mem["episode"] is None or ctx["day"] == 0 and not mem["days_seen"]:
        pass
    mem.setdefault("days_seen", set()).add(ctx["day"])
    mem["episode"] = {"last_day": ctx["day"]}

    if not reset_this_turn:
        _update_drain_ledger(ctx, mem)
        _update_opp_money(ctx, mem)
    _update_shop_tracker(ctx, mem)
    return ctx, mem


def reset_memory(mem):
    mem["prev_inventory"] = None
    mem["prev_shed"] = None
    mem["known_shops"] = []
    mem["town_drain_seen"] = {}
    mem["opp_sales_inferred"] = {}
    mem["our_units_sold"] = {}
    mem["prev_opp_money"] = None
    mem["opp_money_deltas"] = deque(maxlen=OPP_MONEY_WINDOW)
    mem["noop_attempts"] = 0
    mem["invalid_guard"] = 0
    mem["days_seen"] = set()


def _update_drain_ledger(ctx, mem):
    """market_net_drain = diff(market_inventory) - expected_town_consumption.

    Everything that is not explained by town consumption must be player
    activity (ours or opponent's) -> attribute to opponent after subtracting
    our own recorded sells/buys.
    """
    inv_now = ctx["market"].inventory
    prev = mem["prev_inventory"]
    if prev is not None:
        shops = mem.get("known_shops", [])
        for item in PRODUCTS:
            delta = inv_now.get(item, 0) - prev.get(item, 0)
            expected_town = _expected_town_consumption(item, shops, ctx["step"])
            net_player = -delta - expected_town   # positive => players net added
            ours = mem["our_units_sold"].get(item, 0)
            opp_added = net_player - ours
            if abs(opp_added) >= 1:
                mem["opp_sales_inferred"][item] = \
                    mem["opp_sales_inferred"].get(item, 0) + opp_added
    mem["prev_inventory"] = dict(inv_now)


def _expected_town_consumption(item, shops, step):
    """Town consumption that occurred at the PREVIOUS step boundary.

    Consumption happens during interpreter processing of the previous action;
    between two consecutive agent observations exactly one step elapsed.
    """
    prev_step = step - 1
    if prev_step < 0:
        return 0.0
    total = 0.0
    if prev_step % 4 == 0:
        for shop in shops:
            products = SHOPS[shop]
            mult = 2 if len(products) == 1 else 1
            if item in products:
                total += mult
    if prev_step % TURNS_PER_DAY == 0 and item != "FERTILIZER":
        total += 1
    return total


def _update_shop_tracker(ctx, mem):
    current = list(ctx["town"].unlocked_shops)
    if len(current) > len(mem.get("known_shops", [])):
        mem["known_shops"] = current
        log(f"shops now: {current}")


def _update_opp_money(ctx, mem):
    """Track opponent money deltas in a bounded sliding window."""
    opp = ctx.get("opponent_farm")
    if opp is None:
        return
    cur_money = opp.money
    prev = mem["prev_opp_money"]
    if prev is not None:
        delta = cur_money - prev
        mem["opp_money_deltas"].append(delta)
    mem["prev_opp_money"] = cur_money


def record_our_sale(product, units):
    mem = _STATE
    mem["our_units_sold"][product] = mem["our_units_sold"].get(product, 0) + units


def noop_penalty():
    _STATE["noop_attempts"] += 1


def diagnostics():
    m = _STATE
    deltas = list(m["opp_money_deltas"])
    return {
        "noop_attempts": m["noop_attempts"],
        "our_units_sold": dict(m["our_units_sold"]),
        "opp_sales_inferred": {k: round(v, 1) for k, v in m["opp_sales_inferred"].items()},
        "shops_known": list(m.get("known_shops", [])),
        "prev_opp_money": m["prev_opp_money"],
        "opp_money_deltas": deltas,
        "opp_money_delta_sum": sum(deltas),
    }

# ===========================================================================
# END MODULE: state/state_tracker.py
# ===========================================================================

"""Opponent model: public farm scan + market-ledger inference + delta detection.

Phase 1 of the opponent modelling system:
  - snapshot_opponent_farm: compact state representation of all opponent tiles
  - detect_tile_deltas: harvest, planting, animal purchase/collection events
  - infer_turn_transactions: reconcile money + market deltas to detect sales

Phase 2 — Production Forecasting (Pillar 1):
  - forecast_opponent_production: exact forward schedule of harvests/yields
  - get_imminent_harvests: currently ripe uncollected produce on field
  - summarize_opponent_commitments: portfolio allocation percentages

Phase 3 — Shed Inference & Sell Prediction (Pillars 2 & 3):
  - update_opponent_shed_estimate: probabilistic shed reconstruction
  - compute_opponent_sell_probabilities: multi-signal sell scoring
  - predict_imminent_dumps: dump volume estimation
"""





# ---------------------------------------------------------------------------
# Tile-level snapshot helpers
# ---------------------------------------------------------------------------

def _tile_signature(tile):
    """Compact hashable signature of a tile's observable state."""
    if tile.kind == "EMPTY" or tile.kind == "LOCKED":
        return ("EMPTY",) if tile.kind == "EMPTY" else ("LOCKED",)
    if tile.is_animal:
        return ("ANIMAL", tile.animal, tile.yield_units, tile.fed_today,
                tile.cared_today, tile.consecutive_unfed)
    if tile.is_plant:
        return ("PLANT", tile.crop, tile.planted_day, tile.yield_units,
                tile.watered_today, tile.consecutive_unwatered,
                tile.fertilized_until_day)
    # Structure (COOP / PASTURE) with no animal on it
    return ("STRUCTURE", tile.kind)


def snapshot_opponent_farm(opp_farm):
    """Capture a compact state representation of all opponent tiles.

    Returns a dict with:
      - tiles: dict mapping (x,y) -> tile signature tuple
      - money: float
      - hands: list of (x,y) hand positions
      - unlocked: sorted list of unlocked quadrants
      - shed: dict of product counts
    """
    if opp_farm is None:
        return None
    tiles = {}
    for t in opp_farm.iter_tiles():
        tiles[(t.x, t.y)] = _tile_signature(t)
    return {
        "tiles": tiles,
        "money": opp_farm.money,
        "hands": list(opp_farm.hands),
        "unlocked": sorted(opp_farm.unlocked),
        "shed": dict(getattr(opp_farm, "shed", {})),
    }


def snapshot_equal(snap_a, snap_b):
    """True if two snapshots are structurally identical."""
    if snap_a is None or snap_b is None:
        return snap_a is snap_b
    return (snap_a["tiles"] == snap_b["tiles"]
            and snap_a["money"] == snap_b["money"]
            and snap_a["hands"] == snap_b["hands"]
            and snap_a["unlocked"] == snap_b["unlocked"])


# ---------------------------------------------------------------------------
# Delta detection between consecutive snapshots
# ---------------------------------------------------------------------------

def detect_tile_deltas(current_farm, prev_snapshot):
    """Compare current farm tiles to previous snapshot.

    Returns a list of delta dicts, each with:
      - pos: (x,y) position
      - event: str - one of 'harvest', 'plant', 'animal_collect',
        'animal_place', 'animal_death', 'plant_death'
      - details: dict with crop/animal type, old/new yield, etc.
    """
    if prev_snapshot is None or current_farm is None:
        return []

    deltas = []
    prev_tiles = prev_snapshot["tiles"]

    for t in current_farm.iter_tiles():
        pos = (t.x, t.y)
        old_sig = prev_tiles.get(pos)
        new_sig = _tile_signature(t)

        if old_sig == new_sig:
            continue

        old_kind = old_sig[0] if old_sig else "EMPTY"
        new_kind = new_sig[0]

        # --- Harvest events ---
        if new_kind == "EMPTY" and old_kind == "PLANT":
            old_crop = old_sig[1]
            old_yield = old_sig[3] if len(old_sig) > 3 else 0
            deltas.append({
                "pos": pos, "event": "harvest",
                "details": {"crop": old_crop, "yield_units": old_yield},
            })
            continue

        # --- Planting events ---
        if new_kind == "PLANT" and old_kind == "EMPTY":
            deltas.append({
                "pos": pos, "event": "plant",
                "details": {"crop": t.crop, "planted_day": t.planted_day},
            })
            continue

        # --- Animal product collection (yield decreased) ---
        if new_kind == "ANIMAL" and old_kind == "ANIMAL":
            old_animal = old_sig[1]
            new_animal = new_sig[1]
            old_yield = old_sig[2] if len(old_sig) > 2 else 0
            new_yield = new_sig[2] if len(new_sig) > 2 else 0
            if new_yield < old_yield:
                product = ANIMALS.get(new_animal, {}).get("product", "?")
                deltas.append({
                    "pos": pos, "event": "animal_collect",
                    "details": {"animal": new_animal, "product": product,
                                "old_yield": old_yield, "new_yield": new_yield},
                })
            continue

        # --- Animal placement (structure -> animal) ---
        if new_kind == "ANIMAL" and old_kind == "STRUCTURE":
            deltas.append({
                "pos": pos, "event": "animal_place",
                "details": {"animal": t.animal},
            })
            continue

        # --- Animal death (animal -> empty or structure) ---
        if old_kind == "ANIMAL" and new_kind in ("EMPTY", "STRUCTURE"):
            deltas.append({
                "pos": pos, "event": "animal_death",
                "details": {"animal": old_sig[1]},
            })
            continue

        # --- Plant death / decay (plant cleared without harvest) ---
        if new_kind == "EMPTY" and old_kind == "PLANT":
            # Already handled above (harvest case), so this is death
            pass  # redundant guard; harvest covers plant->empty

        # --- Structure added (empty -> structure) ---
        if new_kind == "STRUCTURE" and old_kind == "EMPTY":
            deltas.append({
                "pos": pos, "event": "structure_build",
                "details": {"structure": t.kind},
            })

    return deltas


# ---------------------------------------------------------------------------
# Market + money delta inference
# ---------------------------------------------------------------------------

def infer_turn_transactions(opp_money_delta, market_inventory_delta,
                            town_consumption, our_sales):
    """Reconcile opponent money change with market inventory changes.

    Args:
      opp_money_delta: float, change in opponent money this turn.
      market_inventory_delta: dict {product: delta_inv} for this turn.
        Positive delta = inventory increased (bought). Negative = decreased (sold).
      town_consumption: dict {product: units} consumed by town this turn.
      our_sales: dict {product: units} we sold this turn.

    Returns a dict with:
      - confirmed_sells: dict {product: units} opponent definitely sold.
      - confirmed_buys: dict {product: units} opponent definitely bought.
      - explained_money: float, money change explained by confirmed sells/buys.
      - unexplained_money: float, money delta not explained by known transactions.
    """
    confirmed_sells = {}
    confirmed_buys = {}
    explained_money = 0.0

    for product in PRODUCTS:
        inv_delta = market_inventory_delta.get(product, 0)
        town = town_consumption.get(product, 0)
        ours = our_sales.get(product, 0)

        # Net drain on market = -inv_delta (positive => someone sold)
        net_market_drain = max(0, -inv_delta)
        # Subtract town consumption to isolate player sells
        player_sells = max(0, net_market_drain - town)
        # Subtract our recorded sales to isolate opponent sells
        opp_sells = max(0, player_sells - ours)
        if opp_sells > 0:
            confirmed_sells[product] = opp_sells
            explained_money += opp_sells  # selling adds money

        # Check for opponent buying: inventory increased despite town drain
        if inv_delta > 0 and town > 0:
            opp_bought = inv_delta
            confirmed_buys[product] = opp_bought
            explained_money -= opp_bought  # buying costs money

    return {
        "confirmed_sells": confirmed_sells,
        "confirmed_buys": confirmed_buys,
        "explained_money": explained_money,
        "unexplained_money": opp_money_delta - explained_money,
    }


# ---------------------------------------------------------------------------
# Phase 2 — Production Forecasting (Pillar 1)
# ---------------------------------------------------------------------------

def _ongoing_crop_yield(crop_name, day, fertilized_until_day):
    """Per-cycle yield for an ongoing crop on a given day.

    1 unit base, +1 bonus if fertilized_until_day covers this day.
    """
    base = 1
    if fertilized_until_day >= day:
        base += 1
    return min(base, CROPS[crop_name]["max_yield"])


def forecast_opponent_production(opp_farm, current_day, horizon_days=30):
    """Build an exact forward schedule of the opponent's crop harvests.

    Args:
      opp_farm: FarmView of the opponent's farm (or None).
      current_day: int, the current in-game day (0-indexed).
      horizon_days: int, how many days to project forward (default 30 = full season).

    Returns:
      Dict[str, Dict[int, float]] mapping product -> {day: projected_units}.
      Only includes days within the season (day <= 29).
    """
    if opp_farm is None:
        return {}

    schedule = defaultdict(lambda: defaultdict(float))
    last_day = min(current_day + horizon_days, 29)  # season ends at day 29

    for t in opp_farm.iter_tiles():
        # --- One-time crops ---
        if t.is_plant and not CROPS.get(t.crop, {}).get("ongoing", True):
            cd = CROPS[t.crop]
            harvest_day = t.planted_day + cd["max_yield_day"]

            # Crop mortality: unwatered >= 1 and not watered today => likely death
            if t.consecutive_unwatered >= 1 and not t.watered_today:
                continue  # skip — crop likely dies before maturity

            # Only forecast if harvest is within remaining season
            if current_day < harvest_day <= last_day:
                # Yield: use max_yield as projection (engine caps at max_yield_day)
                # Fertilizer effect: bonus window extends effective yield window
                yield_units = cd["max_yield"]
                # If fertilized, the crop has +1 effective yield per bonus day
                # remaining, but engine caps at max_yield — so just use max_yield
                # since fertilized crops hit max_yield at max_yield_day.
                schedule[t.crop][harvest_day] += yield_units

        # --- Ongoing crops (tomato, strawberry) ---
        if t.is_plant and CROPS.get(t.crop, {}).get("ongoing", False):
            cd = CROPS[t.crop]
            first = t.planted_day + cd["first_yield_day"]
            interval = cd["interval"]

            # Crop mortality check
            if t.consecutive_unwatered >= 1 and not t.watered_today:
                continue

            if interval <= 0:
                continue  # safety — ongoing should always have interval > 0

            # Generate all yield days from first through season end
            day = first
            while day <= last_day:
                if day >= current_day:
                    yld = _ongoing_crop_yield(t.crop, day,
                                              t.fertilized_until_day)
                    schedule[t.crop][day] += yld
                day += interval

        # --- Animals ---
        if t.is_animal and t.animal in ANIMALS:
            info = ANIMALS[t.animal]
            product = info["product"]
            first = t.placed_day + info["first_yield_day"]
            interval = info["interval"]

            # Produce on each interval day through season end.
            # We assume regular collection (opponent clears yield before
            # max_held fills), so each production day is independent.
            day = first
            while day <= last_day:
                if day >= current_day:
                    yld = 1
                    if t.cared_today or t.pending_care_bonus > 0:
                        yld += 1
                    schedule[product][day] += yld
                day += interval

    return {k: dict(v) for k, v in schedule.items()}


def get_imminent_harvests(opp_farm, current_day):
    """Identify crops/animals currently ripe with uncollected yield on field.

    Returns:
      Dict[str, int] mapping product -> ripe_units_on_field.
    """
    if opp_farm is None:
        return {}

    harvests = defaultdict(int)

    for t in opp_farm.iter_tiles():
        # --- One-time crops: ripe if age >= max_yield_day and yield > 0 ---
        if t.is_plant:
            cd = CROPS.get(t.crop)
            if cd is None:
                continue
            age = crop_age(t, current_day)
            if not cd["ongoing"] and age >= cd["max_yield_day"] and t.yield_units > 0:
                harvests[t.crop] += t.yield_units

            # --- Ongoing crops: ripe if on a yield day and yield > 0 ---
            if cd["ongoing"] and t.yield_units > 0:
                first = t.planted_day + cd["first_yield_day"]
                if current_day >= first and (current_day - first) % cd["interval"] == 0:
                    harvests[t.crop] += t.yield_units

        # --- Animals: product ready if yield_units > 0 ---
        if t.is_animal and t.animal in ANIMALS:
            if t.yield_units > 0:
                product = ANIMALS[t.animal]["product"]
                harvests[product] += t.yield_units

    return dict(harvests)


def summarize_opponent_commitments(opp_farm):
    """Summarize the opponent's tile allocation and portfolio percentages.

    Returns:
      Dict with keys:
        - crop_tiles: dict {crop: count}
        - animal_counts: dict {animal_type: count}
        - structure_count: int (COOP + PASTURE, including those with animals)
        - empty_tiles: int
        - locked_tiles: int
        - total_tiles: int
        - allocation_pct: dict {category: percentage_of_total}
    """
    if opp_farm is None:
        return {
            "crop_tiles": {}, "animal_counts": {}, "structure_count": 0,
            "empty_tiles": 0, "locked_tiles": 0, "total_tiles": 0,
            "allocation_pct": {},
        }

    crop_tiles = defaultdict(int)
    animal_counts = defaultdict(int)
    structure_count = 0
    empty_tiles = 0
    locked_tiles = 0
    total = 0

    for t in opp_farm.iter_tiles():
        total += 1
        if t.kind == "LOCKED":
            locked_tiles += 1
        elif t.kind == "EMPTY":
            empty_tiles += 1
        elif t.is_animal:
            animal_counts[t.animal] += 1
        elif t.is_plant:
            crop_tiles[t.crop] += 1
        elif t.kind in ("COOP", "PASTURE"):
            structure_count += 1

    # Allocation percentages
    alloc = {}
    if total > 0:
        for crop, cnt in crop_tiles.items():
            alloc[f"crop_{crop}"] = round(cnt / total * 100, 1)
        for animal, cnt in animal_counts.items():
            alloc[f"animal_{animal}"] = round(cnt / total * 100, 1)
        alloc["empty"] = round(empty_tiles / total * 100, 1)
        alloc["locked"] = round(locked_tiles / total * 100, 1)

    return {
        "crop_tiles": dict(crop_tiles),
        "animal_counts": dict(animal_counts),
        "structure_count": structure_count,
        "empty_tiles": empty_tiles,
        "locked_tiles": locked_tiles,
        "total_tiles": total,
        "allocation_pct": alloc,
    }


# ---------------------------------------------------------------------------
# Phase 3 — Shed Inference & Sell Prediction (Pillars 2 & 3)
# ---------------------------------------------------------------------------

def update_opponent_shed_estimate(prev_shed, harvest_events, inferred_sales,
                                  n_animals, day, hour):
    """Probabilistically reconstruct opponent's shed contents across turns.

    Args:
      prev_shed: dict {product: count} — previous estimated shed state (or None).
      harvest_events: list of delta dicts from detect_tile_deltas with
        event in ('harvest', 'animal_collect').
      inferred_sales: dict {product: units} — opponent sales inferred from
        the market drain ledger this turn.
      n_animals: int — number of opponent animals (for feed deduction).
      day: int — current game day.
      hour: int — current game hour (24h clock).

    Returns:
      dict {product: count} — updated estimated shed state.
    """
    shed = dict(prev_shed) if prev_shed else {}

    # --- Additions: harvest events ---
    for ev in harvest_events:
        if ev["event"] == "harvest":
            product = ev["details"].get("crop", "")
            units = ev["details"].get("yield_units", 0)
            if product and units > 0:
                shed[product] = shed.get(product, 0) + units
        elif ev["event"] == "animal_collect":
            product = ev["details"].get("product", "")
            old_y = ev["details"].get("old_yield", 0)
            new_y = ev["details"].get("new_yield", 0)
            collected = max(0, old_y - new_y)
            if product and collected > 0:
                shed[product] = shed.get(product, 0) + collected

    # --- Subtractions: inferred sales from market ledger ---
    for product, units in inferred_sales.items():
        if units > 0:
            shed[product] = max(0, shed.get(product, 0) - units)

    # --- Subtractions: animal feed at end-of-day rollover ---
    # Animals consume 1 WHEAT each at hour 23->0 boundary
    if hour == 0 and n_animals > 0:
        feed_cost = min(n_animals, shed.get("WHEAT", 0))
        if feed_cost > 0:
            shed["WHEAT"] = shed.get("WHEAT", 0) - feed_cost

    # --- Bounds: clamp non-negative ---
    for p in list(shed.keys()):
        shed[p] = max(0, shed[p])
        if shed[p] == 0:
            del shed[p]

    # --- Bounds: enforce total shed capacity ---
    total = sum(shed.values())
    if total > SHED_CAPACITY:
        # Proportionally shrink each product
        scale = SHED_CAPACITY / total if total > 0 else 0
        for p in shed:
            shed[p] = int(shed[p] * scale)
        # Fix rounding error: trim largest product
        new_total = sum(shed.values())
        if new_total > SHED_CAPACITY and shed:
            biggest = max(shed, key=shed.get)
            shed[biggest] -= (new_total - SHED_CAPACITY)

    return shed


def compute_opponent_sell_probabilities(opp_farm, estimated_shed, ctx, mem):
    """Score each product on [0.0, 1.0] for likelihood of opponent selling.

    Multi-signal heuristic weights:
      1. Shed stock (0.35)
      2. Imminent / unharvested units (0.25)
      3. Shed distance / movement signal (0.20)
      4. Global shed pressure (0.15)
      5. Timing window boost (0.05)

    Args:
      opp_farm: FarmView of opponent's farm (or None).
      estimated_shed: dict {product: count} from update_opponent_shed_estimate.
      ctx: parsed observation context dict.
      mem: persistent memory dict.

    Returns:
      dict {product: sell_probability} on [0.0, 1.0].
    """
    if opp_farm is None:
        return {}

    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)

    # Signal 1: Shed stock weight
    total_shed = sum(estimated_shed.values())
    shed_stock_scores = {}
    for p in PRODUCTS:
        units = estimated_shed.get(p, 0)
        shed_stock_scores[p] = min(1.0, units / 15.0)  # 15 units = full signal

    # Signal 2: Imminent / unharvested units
    imminent = get_imminent_harvests(opp_farm, day)
    imminent_scores = {}
    for p in PRODUCTS:
        units = imminent.get(p, 0)
        imminent_scores[p] = min(1.0, units / 6.0)  # 6 units = full signal

    # Signal 3: Shed distance / movement signal
    shed_tiles = set(SHED_ACCESS_TILES)
    all_positions = []
    for t in opp_farm.iter_tiles():
        if t.is_animal or t.is_plant:
            all_positions.append((t.x, t.y))
    # Check farmer and hands positions
    farmer_pos = getattr(opp_farm, "farmer", (4, 4))
    hand_positions = getattr(opp_farm, "hands", [])
    nearby_count = 0
    for pos in [farmer_pos] + list(hand_positions):
        if pos in shed_tiles:
            nearby_count += 2  # right at shed = very high signal
        else:
            # Manhattan distance to nearest shed tile
            min_dist = min(abs(pos[0] - sx) + abs(pos[1] - sy)
                           for sx, sy in shed_tiles)
            if min_dist <= 1:
                nearby_count += 1
    movement_score = min(1.0, nearby_count / 2.0)

    # Signal 4: Global shed pressure
    pressure = total_shed / SHED_CAPACITY if SHED_CAPACITY > 0 else 0
    pressure_score = min(1.0, max(0.0, (pressure - 0.6) / 0.4)) if pressure >= 0.6 else 0.0

    # Signal 5: Timing window boost
    timing_score = 0.0
    if hour % 4 == 1:  # post-drain sell window
        timing_score = 0.5
    elif hour >= 22:  # end-of-day liquidation push
        timing_score = 0.3
    elif hour % 4 == 0:  # drain just happened, selling imminent
        timing_score = 0.2

    # Combine weighted signals
    W_SHED = 0.35
    W_IMMINENT = 0.25
    W_MOVEMENT = 0.20
    W_PRESSURE = 0.15
    W_TIMING = 0.05

    probs = {}
    for p in PRODUCTS:
        score = (
            W_SHED * shed_stock_scores[p]
            + W_IMMINENT * imminent_scores[p]
            + W_MOVEMENT * movement_score
            + W_PRESSURE * pressure_score
            + W_TIMING * timing_score
        )
        probs[p] = round(min(1.0, max(0.0, score)), 4)

    return probs


def predict_imminent_dumps(opp_farm, estimated_shed, sell_probs, threshold=0.60):
    """Estimate dump volume for products with high sell probability.

    Args:
      opp_farm: FarmView (for drip-slice estimation).
      estimated_shed: dict {product: count}.
      sell_probs: dict {product: probability} from compute_opponent_sell_probabilities.
      threshold: float — minimum probability to flag as imminent dump.

    Returns:
      dict {product: {"probability": float, "estimated_volume": int,
                       "urgency": "HIGH" | "MEDIUM"}}.
    """
    dumps = {}
    drip_slice = 3  # conservative estimate of units per sell order

    for p, prob in sell_probs.items():
        if prob < threshold:
            continue
        shed_units = estimated_shed.get(p, 0)
        if shed_units <= 0:
            continue
        est_vol = min(shed_units, drip_slice)
        urgency = "HIGH" if prob >= 0.80 else "MEDIUM"
        dumps[p] = {
            "probability": prob,
            "estimated_volume": est_vol,
            "urgency": urgency,
        }

    return dumps


# ---------------------------------------------------------------------------
# Legacy helpers (kept for backward compat)
# ---------------------------------------------------------------------------

def opponent_snapshot(ctx, mem):
    """Summarize the opponent's public state each turn (legacy)."""
    opp = ctx["opponent_farm"]
    if opp is None:
        return {}
    ripe_melons = 0
    ripe_crops = {}
    for t in opp.iter_tiles():
        if t.is_plant:
            cd = CROPS.get(t.crop)
            if cd is None:
                continue
            age = crop_age(t, ctx["day"])
            if not cd["ongoing"] and age >= cd["max_yield_day"]:
                ripe_crops[t.crop] = ripe_crops.get(t.crop, 0) + t.yield_units
    animals = sum(1 for t in opp.iter_tiles() if t.is_animal)
    return {
        "money": opp.money,
        "ripe_units": ripe_crops,
        "animals": animals,
        "hands": len(opp.hands),
        "unlocked": sorted(opp.unlocked),
    }


def opponent_primary_product(mem, default="MELON"):
    """Product the opponent most likely holds for sale (from ledger inference)."""
    inferred = mem.get("opp_sales_inferred", {})
    if not inferred:
        return default
    return max(inferred, key=lambda k: inferred[k])

# ===========================================================================
# END MODULE: state/opponent_model.py
# ===========================================================================

"""Shop-unlock adaptive demand scoring and planting pivots."""



def demand_boosts(known_shops):
    """Product -> multiplier reflecting current town shop pressure."""
    boost = {}
    for shop in known_shops:
        for product in SHOPS[shop]:
            boost[product] = boost.get(product, 0) + 1
    return boost


def preferred_filler_crop(boosts, day):
    """Best crop to drop into spare tiles given shop unlocks and calendar.

    - PET_CAFE (carrot): carrots are cheap, fast (3d) -> always viable filler.
    - FARMERS_MARKET: carrots again (4 demanded products, carrot cheapest slot).
    - Ice cream / smoothie / brunch strawberry demand only pays if planted
      early enough for two harvest windows; otherwise fall back to carrots.
    """
    carrot_score = boosts.get("CARROT", 0)
    straw_score = boosts.get("STRAWBERRY", 0) * 2   # higher base price upside
    if straw_score > carrot_score and day <= 8:
        return "STRAWBERRY"
    if carrot_score > 0 or day >= 20:
        return "CARROT"
    return "CARROT"                                  # default cash filler


def react_to_new_shops(ctx, mem, macro):
    """Called daily: update macro.filler_crop from newly unlocked shops."""
    known = mem.get("known_shops", [])
    boosts = demand_boosts(known)
    new_count = len(known)
    prev = macro.get("shops_seen", 0)
    macro["shops_seen"] = new_count
    macro["demand_boosts"] = boosts
    if new_count > prev:
        macro["filler_crop"] = preferred_filler_crop(boosts, ctx["day"])
        macro["shop_event"] = True     # triggers a small carrot seed buy burst
    else:
        macro.setdefault("filler_crop", "CARROT")
        macro["shop_event"] = False
    return macro

# ===========================================================================
# END MODULE: strategy/shop_adapter.py
# ===========================================================================

"""W1: Validated price distributions -> agent-consumable forecasts.

Reads the exhaustive enumeration reference (population-exact statistics over
all 8^8 shop sequences) and exposes decision-grade queries:

    PriceForecast.load()                    # baked table -> npz fallback
    f.expected_price("MELON", 21)           # E[P | day]
    f.prob_above("CARROT", 15, 100)         # P(P > threshold | day)
    f.prob_floor("MELON", 25)               # P(price == $1 | day)
    f.quantile("WOOL", 20, 0.9)             # exact-at-knot quantiles

Bundling constraint: the Kaggle submission is a single file with no repo
access, so numpy lives ONLY inside `from_reference` (dev-time). Runtime uses
a plain-dict table that is either imported from the generated
`baked_price_table.py` module or passed in directly. Regenerate with:

    python price_forecast.py --build-table

Reference schema produced by simulations/monte_carlo_shops/exhaustive_enumerator.py.
"""



# Repo layout: <root>/agent/strategy/price_forecast.py
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE)) if "_HERE" in globals() else os.getcwd()
DEFAULT_REFERENCE = os.path.join(
    _REPO_ROOT, "simulations", "monte_carlo_shops", "results", "exhaustive",
    "town_only_reference.npz")
DEFAULT_BAKED = os.path.join(_HERE, "baked_price_table.py")

QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
TABLE_VERSION = 1


def _round_floats(value, nd=4):
    if isinstance(value, float):
        return round(value, nd)
    if isinstance(value, list):
        return [_round_floats(v, nd) for v in value]
    if isinstance(value, dict):
        return {k: _round_floats(v, nd) for k, v in value.items()}
    return value


class PriceForecast:
    """Decision-grade view over an exhaustive price reference table.

    DAY-CELL SEMANTICS (important for consumers): cell `day=h` holds the
    market state after day h's town-consumption ticks are applied -- i.e. the
    state sellers actually face during day h's action window (the town center
    drains at hour 0, before the t%4==1 sell windows). Example: day 0 already
    includes one TC tick, so WHEAT day-0 E[P] = quote(I0 - 1) = $26.
    """

    def __init__(self, table):
        if table.get("version") != TABLE_VERSION:
            raise ValueError(f"unsupported price table version {table.get('version')}")
        self.table = table
        self.products = list(table["products"])
        self.n_days = int(table["days"])
        self.scenario = table.get("scenario", "unknown")
        self._idx = {p: i for i, p in enumerate(self.products)}
        # Sanitized per-product threshold anchors: grid rows are padded with
        # trailing $1 entries; tail columns for equal thresholds are equal,
        # so keep first occurrence and sort ascending.
        self._anchors = {}
        for p in self.products:
            pairs = {}
            for j, gval in enumerate(table["grid"][p]):
                gval = int(gval)
                if gval not in pairs:
                    pairs[gval] = table["tail_prob"][p][j]
            self._anchors[p] = sorted(pairs.items())

    # ------------------------------------------------------------ loaders --
    @classmethod
    def from_table(cls, table):
        return cls(table)

    @classmethod
    def from_reference(cls, path=DEFAULT_REFERENCE):
        """Dev-time loader (requires numpy); produces the compact table."""
        import numpy as np  # dev-time only: never imported at submission runtime

        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        products = meta["products"]
        n_days = int(z["mean"].shape[0])
        count = float(z["count"])

        def by_product(arr):
            return {p: [round(float(v), 4) for v in arr[:, i]]
                    for i, p in enumerate(products)}

        hist = z["hist"].astype(np.int64)
        cdf = np.cumsum(hist, axis=-1)
        quantiles = {}
        for level in QUANTILE_LEVELS:
            key = f"q{int(round(level * 100)):02d}"
            target = level * count
            vals = {}
            for i, p in enumerate(products):
                col = []
                for d in range(n_days):
                    row = cdf[d, i]
                    v = int(np.searchsorted(row, target, side="left"))
                    col.append(min(v, HIST_CAP))
                vals[p] = col
            quantiles[key] = vals

        grid = z["grid"]
        tail = z["tail_prob"]          # (n_prod, G, n_days)
        grid_t = {}
        tail_t = {}
        for i, p in enumerate(products):
            seen = {}
            for j in range(grid.shape[1]):
                gval = int(grid[i, j])
                if gval not in seen:
                    seen[gval] = [round(float(v), 6) for v in tail[i, j]]
            pairs = sorted(seen.items())
            grid_t[p] = [g for g, _ in pairs]
            tail_t[p] = [t for _, t in pairs]

        table = {
            "version": TABLE_VERSION,
            "scenario": meta.get("scenario", "unknown"),
            "complete_enumeration": bool(meta.get("complete_enumeration", False)),
            "count": int(count),
            "days": n_days,
            "products": products,
            "mean": by_product(z["mean"]),
            "std": by_product(z["std"]),
            "floor_prob": by_product(z["floor_prob"]),
            "quantiles": quantiles,
            "grid": grid_t,
            "tail_prob": tail_t,
        }
        return cls(_round_floats(table))

    @staticmethod
    def load(reference_path=None):
        """Baked module first, then npz reference. Raises if neither exists."""
        if "PRICE_TABLE" in globals():
            return PriceForecast.from_table(globals()["PRICE_TABLE"])
        try:
            from baked_price_table import PRICE_TABLE      # bundled flat layout
            return PriceForecast.from_table(PRICE_TABLE)
        except ImportError:
            pass
        try:
            from strategy.baked_price_table import PRICE_TABLE   # package layout
            return PriceForecast.from_table(PRICE_TABLE)
        except ImportError:
            pass
        path = reference_path or DEFAULT_REFERENCE
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"no baked_price_table and no reference at {path}; "
                f"build one via: python price_forecast.py --build-table")
        return PriceForecast.from_reference(path)

    # ----------------------------------------------------------- queries ---
    def _day(self, day):
        return max(0, min(int(day), self.n_days - 1))

    def expected_price(self, product, day):
        return self.table["mean"][product][self._day(day)]

    def std_price(self, product, day):
        return self.table["std"][product][self._day(day)]

    def prob_floor(self, product, day):
        return self.table["floor_prob"][product][self._day(day)]

    def prob_above(self, product, day, threshold):
        """P(price > threshold | day). Exact on grid anchors; linear interp
        between anchors; clamped to anchor values outside the grid range."""
        anchors = self._anchors[product]
        d = self._day(day)
        t = float(threshold)
        if t <= anchors[0][0]:
            return anchors[0][1][d]
        if t >= anchors[-1][0]:
            return anchors[-1][1][d]
        for (g0, t0), (g1, t1) in zip(anchors, anchors[1:]):
            if g0 < t <= g1:
                w = (t - g0) / float(g1 - g0)
                return t0[d] + w * (t1[d] - t0[d])
        return anchors[-1][1][d]

    def quantile(self, product, day, q):
        """Price quantile, piecewise-linear across the baked knot levels.

        Exact at baked knots (integer prices); +/- $1 between knots.
        """
        qs = self.table["quantiles"]
        keys = sorted(qs.keys())
        levels = [int(k[1:]) / 100.0 for k in keys]
        qq = min(max(float(q), 0.0), 1.0)
        d = self._day(day)
        vals = []
        for k in keys:
            row = qs[k][product]
            vals.append(row[d] if d < len(row) else row[-1])
        if qq <= levels[0]:
            return vals[0]
        if qq >= levels[-1]:
            return vals[-1]
        for l0, l1, v0, v1 in zip(levels, levels[1:], vals, vals[1:]):
            if l0 <= qq <= l1:
                w = (qq - l0) / (l1 - l0) if l1 > l0 else 0.0
                return v0 + w * (v1 - v0)
        return vals[-1]

    def summary(self, day):
        out = {"scenario": self.scenario, "day": self._day(day)}
        for p in self.products:
            out[p] = {
                "E": self.expected_price(p, day),
                "p_floor": self.prob_floor(p, day),
            }
        return out


HIST_CAP = 20000   # overflow bucket index used by the enumerator's histogram


def export_table_literal(table):
    """Python source literal for baking into the bundled submission."""
    import pprint
    return "# Auto-generated by price_forecast.py --build-table. Do not edit.\n" \
           "PRICE_TABLE = " + pprint.pformat(_round_floats(table, 4),
                                             sort_dicts=False, width=96) + "\n"


def write_baked_table(table, path=DEFAULT_BAKED):
    src = export_table_literal(table.table if isinstance(table, PriceForecast)
                               else table)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    return path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="W1 price forecast utility")
    ap.add_argument("--reference", type=str, default=DEFAULT_REFERENCE)
    ap.add_argument("--build-table", action="store_true",
                    help=f"write compact table to {DEFAULT_BAKED}")
    ap.add_argument("--print-sample", type=int, default=None,
                    help="print E[P]/P(floor) for every product on a given day")
    args = ap.parse_args(argv)

    fc = PriceForecast.from_reference(args.reference)
    print(f"reference: scenario={fc.scenario} complete="
          f"{fc.table['complete_enumeration']} days={fc.n_days} "
          f"sequences={fc.table['count']:,}")
    if args.print_sample is not None:
        for line in json.dumps(fc.summary(args.print_sample), indent=2).splitlines():
            print(line)
    if args.build_table:
        path = write_baked_table(fc)
        size_kb = os.path.getsize(path) / 1024
        print(f"baked table -> {path} ({size_kb:.1f} KB)")
    return fc


if __name__ == "__main__":
    main()

# ===========================================================================
# END MODULE: strategy/price_forecast.py
# ===========================================================================

"""Pillar 5: Actionable Opponent Responses — Tactical Advisor.

Translates raw opponent observations into structured guidance that
MacroPlanner and MarketBrain can consume:

  - supply_adjustment: per-product extra future supply (opp production * weight)
    so MacroPlanner's _crop_score penalises crowded commodities.
  - preempt_sell: products to sell immediately before opponent dumps.
  - delay_sell: products to hold because opponent just crashed the price.
  - counter_pick: shop-demanded products opponent is completely ignoring.
  - opp_shed_pressure: overall opponent shed pressure (0.0 to 1.0).
"""







# ---------------------------------------------------------------------------
# Advice dataclass
# ---------------------------------------------------------------------------

@dataclass
class OpponentAdvice:
    """Structured guidance produced by build_opponent_advice."""
    supply_adjustment: Dict[str, float] = field(default_factory=dict)
    preempt_sell: List[str] = field(default_factory=list)
    delay_sell: List[str] = field(default_factory=list)
    counter_pick: List[str] = field(default_factory=list)
    opp_shed_pressure: float = 0.0

    def to_dict(self):
        return {
            "supply_adjustment": dict(self.supply_adjustment),
            "preempt_sell": list(self.preempt_sell),
            "delay_sell": list(self.delay_sell),
            "counter_pick": list(self.counter_pick),
            "opp_shed_pressure": round(
                max(0.0, min(1.0, self.opp_shed_pressure)), 4,
            ),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPLY_ADJUSTMENT_WEIGHT = 0.50     # opp projected units * weight
SUPPLY_PROJECTION_DAYS = 12         # forward projection horizon
PREEMPT_SELL_THRESHOLD = 0.65       # opp sell probability >= this triggers
DELAY_PRICE_DEPRESSION_PCT = 0.80   # price below 80 % of expected = depressed
DELAY_RECENT_TURNS = 3              # look back N turns for recent dumps
COUNTER_PICK_DEMAND_MIN = 0.01      # minimum town demand signal (boost > 0)


# ---------------------------------------------------------------------------
# Core advisor
# ---------------------------------------------------------------------------

def build_opponent_advice(opp_state, ctx, forecast, boosts=None):
    """Translate opponent observations into actionable OpponentAdvice.

    Args:
      opp_state: dict with keys:
        - estimated_shed: dict {product: count}
        - sell_probs: dict {product: probability}  [0.0, 1.0]
        - opp_sales_inferred: dict {product: cumulative_inferred_units}
        - shed_pressure: float  [0.0, 1.0]
        - forecast: dict {product: {day: units}} from forecast_opponent_production
      ctx: parsed observation dict with 'farm', 'private', 'day', 'hour', etc.
      forecast: dict {product: {day: units}} from forecast_opponent_production
        (if not in opp_state, this is used as the primary forecast source).
      boosts: dict {product: float} optional town demand / shop boosts.
        Keyed by product; values > 0 indicate active town demand.

    Returns:
      OpponentAdvice with all fields populated.
    """
    advice = OpponentAdvice()

    estimated_shed = opp_state.get("estimated_shed", {})
    sell_probs = opp_state.get("sell_probs", {})
    opp_sales = opp_state.get("opp_sales_inferred", {})
    shed_pressure = opp_state.get("shed_pressure", 0.0)
    fc = forecast or opp_state.get("forecast", {})
    # Handle ctx["private"] as either dict or object with .shed attribute
    if ctx and "private" in ctx:
        priv = ctx["private"]
        our_shed = priv.shed if hasattr(priv, "shed") else (priv.get("shed", {}) if isinstance(priv, dict) else {})
    else:
        our_shed = {}
    day = ctx.get("day", 0) if ctx else 0

    # ---- 5a. Anti-Glut Supply Adjustment --------------------------------
    advice.supply_adjustment = _compute_supply_adjustment(fc, day)

    # ---- 5b. Pre-emptive Rush Selling -----------------------------------
    advice.preempt_sell = _compute_preempt_sell(sell_probs, our_shed)

    # ---- 5c. Sell Delay / Post-Crash Hold -------------------------------
    advice.delay_sell = _compute_delay_sell(
        opp_sales, our_shed, fc, day, ctx,
    )

    # ---- 5d. Counter-Pick Monopoly Detection ----------------------------
    advice.counter_pick = _compute_counter_pick(boosts, opp_state)

    # ---- 5e. Shed Pressure Pass-Through ---------------------------------
    advice.opp_shed_pressure = float(max(0.0, min(1.0, shed_pressure)))

    return advice


# ---------------------------------------------------------------------------
# Sub-computations
# ---------------------------------------------------------------------------

def _compute_supply_adjustment(forecast, current_day):
    """Project opponent production over next SUPPLY_PROJECTION_DAYS."""
    adj = {}
    if not forecast:
        return adj
    horizon = current_day + SUPPLY_PROJECTION_DAYS
    for product, schedule in forecast.items():
        total = 0.0
        for d, units in schedule.items():
            if current_day <= d <= horizon:
                total += units
        if total > 0:
            adj[product] = round(total * SUPPLY_ADJUSTMENT_WEIGHT, 4)
    return adj


def _compute_preempt_sell(sell_probs, our_shed):
    """Flag products we hold where opponent sell prob >= threshold."""
    result = []
    if not sell_probs:
        return result
    for product, prob in sorted(sell_probs.items(),
                                key=lambda kv: -kv[1]):
        if prob < PREEMPT_SELL_THRESHOLD:
            continue
        if our_shed.get(product, 0) <= 0:
            continue
        result.append(product)
    return result


def _compute_delay_sell(opp_sales, our_shed, forecast, current_day, ctx):
    """Flag products opponent recently dumped causing depressed prices."""
    result = []
    if not opp_sales or not our_shed:
        return result

    for product, cum_units in opp_sales.items():
        if cum_units <= 0:
            continue
        if our_shed.get(product, 0) <= 0:
            continue

        # Compute expected price from forecast to check depression
        expected = 0.0
        if product in forecast:
            # Use nearest forecast day
            best_day = min(forecast[product].keys(),
                           key=lambda d: abs(d - current_day),
                           default=None)
            if best_day is not None:
                expected = forecast[product][best_day]

        # Get current spot price from market inventory
        market_obj = ctx.get("market") if ctx else None
        if isinstance(market_obj, dict):
            inv = market_obj.get("inventory", market_obj)
        else:
            inv = getattr(market_obj, "inventory", {}) if market_obj else {}
        current_inv = inv.get(product, 10000)

        # Import market_price at function scope to avoid circular import issues
        from market.price_math import market_price
        spot = market_price(product, current_inv)

        # Check if price is depressed relative to expected
        if expected > 0 and spot < expected * DELAY_PRICE_DEPRESSION_PCT:
            result.append(product)

    return result


def _compute_counter_pick(boosts, opp_state):
    """Find shop-demanded products opponent completely ignores."""
    result = []
    if not boosts:
        return result

    # Get opponent commitment summary — check crop and animal counts
    opp_commitments = opp_state.get("commitments", {})
    crop_tiles = opp_commitments.get("crop_tiles", {})
    animal_counts = opp_state.get("animal_counts", {})

    # Collect all products opponent is producing
    opp_products = set()
    for product, count in crop_tiles.items():
        if count > 0:
            opp_products.add(product)
    for animal, count in animal_counts.items():
        if count > 0:
            # Map animal to its product
            animal_product_map = {
                "GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL",
            }
            if animal in animal_product_map:
                opp_products.add(animal_product_map[animal])

    # Find products with demand but zero opponent commitment
    for product, demand in boosts.items():
        if demand > COUNTER_PICK_DEMAND_MIN and product not in opp_products:
            result.append(product)

    return sorted(result)

# ===========================================================================
# END MODULE: strategy/opponent_advisor.py
# ===========================================================================

"""BFS pathfinding on the 10x10 farm grid.

LOCKED tiles are fully PASSABLE traversal nodes (mechanic: movement onto
locked tiles is allowed; only tile OPERATIONS no-op there). The shed is
reachable from all four center tiles regardless of lock status.
"""


MOVES = [("NORTH", (0, -1)), ("SOUTH", (0, 1)),
         ("EAST", (1, 0)), ("WEST", (-1, 0))]


def neighbors(pos, board=10):
    x, y = pos
    for name, (dx, dy) in MOVES:
        nx, ny = x + dx, y + dy
        if 0 <= nx < board and 0 <= ny < board:
            yield name, (nx, ny)


def bfs_first_step(start, goal, board=10):
    """First move direction on a shortest path start->goal.

    Grid topology is uniform (all tiles passable), so BFS is overkill but
    kept per architecture; returns None when already at goal.
    """
    if tuple(start) == tuple(goal):
        return None
    prev = {tuple(start): None}
    q = deque([tuple(start)])
    while q:
        cur = q.popleft()
        if cur == tuple(goal):
            break
        for name, nxt in neighbors(cur, board):
            if nxt not in prev:
                prev[nxt] = (cur, name)
                q.append(nxt)
    if tuple(goal) not in prev:
        return None
    # walk back to the edge right after start
    cur = tuple(goal)
    while prev[cur][0] != tuple(start):
        cur = prev[cur][0]
    return prev[cur][1]


def path_length(start, goal, board=10):
    sx, sy = start
    gx, gy = goal
    return abs(sx - gx) + abs(sy - gy)


def nearest_pos(units_positions, targets):
    """Greedy assignment helper: for each target, the closest unit index."""
    out = {}
    remaining = list(range(len(units_positions)))
    for target in sorted(targets, key=lambda t: min(
            path_length(units_positions[i], t) for i in remaining)):
        i = min(remaining, key=lambda i: path_length(units_positions[i], target))
        out[target] = i
        remaining.remove(i)
    return out

# ===========================================================================
# END MODULE: execution/pathfinding.py
# ===========================================================================

"""Unit action emission: movement queues + tile operations per unit.

Each unit (farmer idx 0, hands idx 1+) gets ONE list-action per turn:
either a move toward the task target or the tile/shed operation itself.
"""



def step_toward(unit_pos, target_pos, board=10):
    return bfs_first_step(tuple(unit_pos), tuple(target_pos), board)


def emit_action(task, ctx):
    """Return the list-action for `task` given the assigned unit's position.

    Task shape: {"op": str, "target": (x,y) | None, "args": list}
    Ops with target=None execute immediately (should be none here).
    """
    op = task["op"]
    target = task.get("target")
    args = task.get("args", [])
    pos = tuple(task["unit_pos"])
    board = 10

    if target is not None and pos != tuple(target):
        move = step_toward(pos, target, board)
        if move is None:
            # unreachable/occupied edge: fall through to op attempt
            pass
        else:
            return [move]

    if op in ("NORTH", "SOUTH", "EAST", "WEST", "PASS"):
        return [op]
    if op == "PICKUP":
        return ["PICKUP", *args]
    if op == "PLACE":
        return ["PLACE", *args]
    return [op] if not args else [op, *args]


def needs_shed_adjacent(op):
    return op in ("PICKUP", "DROP") or (op == "PLACE_SHED")


def reroute_to_shed_access(unit_pos):
    """Closest shed-access tile for PICKUP/DROP staging."""
    best = None
    best_d = 10 ** 9
    for tile in [(4, 4), (5, 4), (4, 5), (5, 5)]:
        d = abs(tile[0] - unit_pos[0]) + abs(tile[1] - unit_pos[1])
        if d < best_d:
            best_d = d
            best = tile
    return best

# ===========================================================================
# END MODULE: execution/unit_controller.py
# ===========================================================================

"""Per-turn prioritized task construction + greedy distance assignment.

v5.9: Action-budget allocator with utilization tracking.

Engine facts encoded here:
  - One action per unit per turn; moves and ops are mutually exclusive.
  - HANDS HIRED THIS TURN CANNOT ACT THIS TURN: interpreter applies unit
    actions BEFORE _process_market() (where HIRE appends to farm["hands"]),
    so a just-hired hand's position lookup returns None and its action is
    dropped. Hands first act on turn T+1. Scheduling therefore dispatches to
    currently-observed hands only; new hires join the roster next turn.
  - Seeds bought this turn are likewise only PLANTable next turn (same
    farm-before-market ordering).
  - A plant with consecutive_unwatered == 1 dies at end-of-day unless watered
    TODAY (urgent survival).
  - One-time crops start decaying the day after max_yield_day -> harvest on
    max_yield_day morning at the latest.
  - Animals produce during end-of-day refresh when (day+1 - placed -
    first_yield_day) % interval == 0; feeding must be done BEFORE that refresh,
    and an unfed production day wipes the banked care bonus.
  - fertilizer_available flips True at end-of-day; collect it any time next day.
"""


# v5.9: Daily utilization tracking (accumulated across all 24 hours of each day)
_daily_log = {}
_daily_accum = {}

def get_daily_log():
    """Return the utilization log for the current episode."""
    return _daily_log

def reset_daily_log():
    """Reset utilization log at start of new episode."""
    global _daily_log, _daily_accum
    _daily_log = {}
    _daily_accum = {}

def _record_turn_utilization(ctx, n_units, actions_taken):
    """Accumulate hourly utilization and finalize daily log at hour 23."""
    day, hour = ctx["day"], ctx["hour"]
    if day not in _daily_accum:
        _daily_accum[day] = {"available": 0, "used": 0, "idle": 0, "idle_causes": []}
    
    used = sum(1 for a in actions_taken.values() if a != ["PASS"])
    avail = n_units
    idle = max(0, avail - used)
    
    _daily_accum[day]["available"] += avail
    _daily_accum[day]["used"] += used
    _daily_accum[day]["idle"] += idle
    if idle > 0:
        _daily_accum[day]["idle_causes"].append("no_tasks" if used == 0 else "partial_idle")
        
    if hour == 23 or ctx.get("step", 0) % TURNS_PER_DAY == 23:
        tot_avail = _daily_accum[day]["available"]
        tot_used = _daily_accum[day]["used"]
        tot_idle = _daily_accum[day]["idle"]
        shed_cnt = sum(ctx["private"].shed.values()) if ctx.get("private") else 0
        unlocked_cnt = len(ctx["farm"].unlocked) if ctx.get("farm") else 1
        n_hands = len(ctx["farm"].hands) if ctx.get("farm") else 0
        from market.order_builder import hire_total_cost
        
        _daily_log[day] = {
            "actions_available": tot_avail,
            "actions_used": tot_used,
            "idle_actions": tot_idle,
            "utilization_pct": round(100.0 * tot_used / max(1, tot_avail), 1),
            "shed_occupancy": shed_cnt,
            "quadrant_ownership": unlocked_cnt,
            "daily_hires": n_hands,
            "hire_cost": hire_total_cost(n_hands),
            "idle_cause": "queue_empty" if tot_idle > 0 else None,
        }


def farm_pos_of(ctx):
    return ctx["farm"].farmer


def produces_today(tile, day):
    """True if this animal's production fires at END-of-day refresh today."""
    info = ANIMALS.get(tile.animal)
    if info is None:
        return False
    since_first = day + 1 - tile.placed_day - info["first_yield_day"]
    return since_first >= 0 and since_first % info["interval"] == 0


def build_tasks(ctx, macro):
    """Construct the prioritized TaskList for this turn."""
    day, hour = ctx["day"], ctx["hour"]
    tasks = []

    def add(priority, op, target=None, args=None, kind="", meta=None):
        tasks.append({"priority": priority, "op": op, "target": target,
                      "args": args or [], "kind": kind, "meta": meta or {}})

    # ---------------- crops ----------------
    water_starved = False
    plants = [t for t in ctx["farm"].iter_tiles() if t.is_plant]
    need_water = []
    for t in plants:
        cd = CROPS.get(t.crop)
        if cd is None:
            continue
        age = crop_age(t, day)
        mature_one_time = (not cd["ongoing"]) and age >= cd["max_yield_day"]
        # decay-imminent harvest (one-time at/after max day, still alive)
        if t.yield_units > 0 and mature_one_time:
            add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_decay")
        elif t.yield_units > 0 and cd["ongoing"]:
            add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing")
        elif t.yield_units >= cd["max_yield"] and not cd["ongoing"]:
            add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_full")

        if not t.watered_today and hour < 23:
            dying_tomorrow = t.consecutive_unwatered >= 1
            if dying_tomorrow:
                # Guardrail 2: mandatory survival watering
                need_water.append((PRIORITY_URGENT_SURVIVAL, t))
            elif needs_water_today(t, day):
                prio = PRIORITY_BONUS_WATER if in_bonus_window(t, day) else 30
                if not macro.watering_enabled and day == 28 and in_bonus_window(t, day):
                    cd = CROPS.get(t.crop, {})
                    harvestable_by_29 = (t.planted_day is not None
                                         and t.planted_day + cd.get("max_yield_day", 99) <= 29)
                    if not harvestable_by_29:
                        continue
                need_water.append((prio, t))

    for prio, t in need_water:
        add(prio, "WATER", t.pos, kind="water")

    # ---------------- fertilizer application (Strawberries, Tomatoes, & Surplus Arbitrage) ----
    fert_in_shed = int(ctx["private"].shed.get("FERTILIZER", 0)) if ctx.get("private") else 0
    fert_held = sum(int(inv.get("FERTILIZER", 0)) for inv in (ctx["private"].inventories if ctx.get("private") else []))
    total_fert = fert_in_shed + fert_held
    
    if total_fert > 0 and hour < 20:
        # Live fertilizer spot price from market
        fert_spot_price = ctx["market"].prices.get("FERTILIZER", 100) if ctx.get("market") else 100
        
        tier1_strawberry = []
        tier2_tomato = []
        tier3_wheat = []
        tier4_carrot = []
        
        for t in plants:
            if t.fertilized_until_day < day:
                age = crop_age(t, day)
                # Tier 1: Strawberry 2-application precision (Ages 9-10 covers 10 & 12; Ages 13-14 covers 14 & 16)
                if t.crop == "STRAWBERRY" and (9 <= age <= 10 or 13 <= age <= 14):
                    tier1_strawberry.append(t.pos)
                # Tier 2: Tomato 2-application precision (Ages 7-8 covers 8, 9, 10; Ages 10-11 covers 11)
                elif t.crop == "TOMATO" and (7 <= age <= 8 or 10 <= age <= 11):
                    tier2_tomato.append(t.pos)
                # Tier 3: Surplus Wheat Arbitrage (applies when market price < $50, window ages 1-2)
                elif fert_spot_price < 50 and t.crop == "WHEAT" and (1 <= age <= 2):
                    tier3_wheat.append(t.pos)
                # Tier 4: Surplus Carrot Arbitrage (applies when market price < $35, window ages 1-2)
                elif fert_spot_price < 35 and t.crop == "CARROT" and (1 <= age <= 2):
                    tier4_carrot.append(t.pos)
                    
        # Prioritize Tier 1 -> Tier 2 -> Tier 3 -> Tier 4
        all_fert_targets = tier1_strawberry + tier2_tomato + tier3_wheat + tier4_carrot
        
        for pos in all_fert_targets[:total_fert]:
            add(PRIORITY_FERTILIZE_CROP, "FERTILIZE", pos, kind="fertilize_crop")
            
        # Stage fertilizer pickup from shed if needed
        needed_pickup = len(all_fert_targets[:total_fert]) - fert_held
        if needed_pickup > 0 and fert_in_shed > 0:
            grab_fert = min(fert_in_shed, needed_pickup)
            farmer_pos = tuple(farm_pos_of(ctx))
            target = min(SHED_ACCESS_TILES,
                         key=lambda tp: abs(tp[0] - farmer_pos[0]) + abs(tp[1] - farmer_pos[1]))
            add(PRIORITY_FEED_STAGING + 1, "PICKUP", tuple(target),
                args=["FERTILIZER", int(grab_fert)], kind="pickup_fertilizer")

    # ---------------- animals ----------------
    feeds_due = 0
    for t in ctx["farm"].iter_tiles():
        if not t.is_animal:
            continue
        feed_now = False
        if t.consecutive_unfed >= 1 and not t.fed_today and hour < 23:
            add(PRIORITY_URGENT_SURVIVAL - 1, "FEED", t.pos,
                kind="feed_rescue", meta={"wheat": 1})
            feed_now = True
        elif produces_today(t, day) and not t.fed_today:
            add(PRIORITY_PROD_DAY_FEED, "FEED", t.pos,
                kind="feed_prod", meta={"wheat": 1})
            feed_now = True
        elif not t.fed_today and hour < 20 and macro.feeding_enabled:
            add(PRIORITY_CARE_ANIMAL - 5, "FEED", t.pos, kind="feed_off",
                meta={"wheat": 1})
            feed_now = True
        feeds_due += 1 if feed_now else 0
        if t.yield_units > 0:
            add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_animal")
        if t.fertilizer_available:
            add(PRIORITY_FERT_COLLECT, "COLLECT_FERTILIZER", t.pos, kind="fert")
        want_care = macro.feeding_enabled and (CARE_GEESE or t.animal != "GOOSE")
        if want_care and not t.cared_today and hour < 21:
            add(PRIORITY_CARE_ANIMAL, "CARE", t.pos, kind="care")

    # WHEAT STAGING: engine FEED consumes the UNIT's inventory (never the
    # shed), so staged PICKUP tasks must run before any FEED can succeed.
    if feeds_due > 0:
        held = sum(int(inv.get("WHEAT", 0))
                   for inv in ctx["private"].inventories)
        shed_wheat = int(ctx["private"].shed.get("WHEAT", 0))
        grab = min(shed_wheat, max(feeds_due - held, 0))
        if grab > 0:
            farmer_pos = tuple(farm_pos_of(ctx))
            target = min(SHED_ACCESS_TILES,
                         key=lambda tp: abs(tp[0] - farmer_pos[0])
                         + abs(tp[1] - farmer_pos[1]))
            add(PRIORITY_FEED_STAGING, "PICKUP", tuple(target),
                args=["WHEAT", int(grab)], kind="pickup_wheat")

    # ---------------- planting queue (seed-conflict-safe) ----------------
    seeds = ctx["private"].seeds
    wanted_plants = list(macro.plant_queue)  # [(pos, crop)]
    if hour <= 18 and macro.watering_enabled:
        by_crop = {}
        for pos, crop in wanted_plants:
            if seeds.get(crop, 0) > by_crop.get(crop, 0):
                by_crop[crop] = by_crop.get(crop, 0) + 1
                add(PRIORITY_PLANT_AND_WATER, "PLANT", pos, args=[crop],
                    kind="plant", meta={"paired_water": True})
            else:
                continue  # skip this crop's remaining instances, keep processing others

    # ---------------- structures & animals ----------------
    for pos in macro.build_queue[:2]:
        add(PRIORITY_BUILD_STRUCTURE, macro.build_op, pos, kind="build")
    for task in macro.place_queue[:2]:
        add(PRIORITY_PLACE_ANIMAL, task["op"], task.get("target"),
            args=task.get("args", []),
            kind=task.get("kind", "place_animal"))

    # ---------------- weeds ----------------
    blocked = {tuple(p) for p, _ in macro.plant_queue}
    for t in ctx["farm"].iter_tiles():
        if t.kind == "WEED" and ctx["farm"].quadrant_of(t.pos) in ctx["farm"].unlocked and hour < 23:
            prio = PRIORITY_WEED_DIG + 15 if t.pos in blocked else PRIORITY_WEED_DIG
            add(prio, "DIG", t.pos, kind="dig")

    return tasks


def assign_tasks(tasks, ctx, extra_units=()):
    """Greedy closest-unit dispatch. Returns per-unit actions + bookkeeping.
    
    v5.9: Tracks daily utilization and logs idle actions.
    """
    farm = ctx["farm"]
    units = [(0, tuple(farm.farmer))]
    for i, h in enumerate(farm.hands):
        units.append((i + 1, tuple(h)))
    for idx, pos in extra_units:
        units.append((idx, tuple(pos)))
    pos_by_idx = dict(units)

    # Holder map for PLACE tasks: engine PLACE requires the ACTING unit to
    # hold the animal, so dispatch must prefer/require holding units.
    holders = {}
    private = ctx.get("private")
    if private is not None:
        for u_idx, inv in enumerate(private.inventories):
            for item, cnt in (inv or {}).items():
                if cnt > 0:
                    holders.setdefault(item, []).append(u_idx)

    def _eligible(task):
        """Units that could execute this task this turn without a no-op."""
        if task["op"] == "PLACE" and task.get("args"):
            item = task["args"][0]
            if item in ANIMALS:
                return set(holders.get(item, []))   # empty => defer, don't no-op
        elif task["op"] == "FERTILIZE":
            return set(holders.get("FERTILIZER", []))
        elif task["op"] == "FEED":
            return set(holders.get("WHEAT", []))
        return None                                  # no restriction

    busy = set()
    assignment = {}          # unit_idx -> task
    deferred_place = []
    for task in sorted(tasks, key=lambda t: -t["priority"]):
        eligible = _eligible(task)
        if eligible is not None and not eligible:
            deferred_place.append(task)               # nobody holds it yet
            continue
        target = task.get("target") or tuple(farm.farmer)
        # Explicit locked-quadrant task guard: never assign operations on locked land
        if task["op"] not in ("PICKUP", "PASS") and farm.quadrant_of(target) not in farm.unlocked:
            continue
        best, best_d = None, 10 ** 9
        for idx, pos in units:
            if idx in busy:
                continue
            if eligible is not None and idx not in eligible:
                continue
            d = abs(pos[0] - target[0]) + abs(pos[1] - target[1])
            if d < best_d:
                best, best_d = idx, d
        if best is None:
            continue
        busy.add(best)
        task["unit_pos"] = pos_by_idx[best]
        assignment[best] = task

    # v5.9: Fallback assignment for idle units to guarantee zero wasted actions
    # Default fallback priority: COLLECT_FERTILIZER -> WATER_MATURE/UNWATERED -> DIG_WEED
    unassigned_units = [idx for idx, _ in units if idx not in busy]
    if unassigned_units:
        targeted_positions = {tuple(t["target"]) for t in assignment.values() if t.get("target")}
        
        # 1. Fallback: collect any available fertilizer
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_animal and t.fertilizer_available and tuple(t.pos) not in targeted_positions:
                best_u = min(unassigned_units, key=lambda u: abs(pos_by_idx[u][0] - t.x) + abs(pos_by_idx[u][1] - t.y))
                unassigned_units.remove(best_u)
                busy.add(best_u)
                task = {"priority": 10, "op": "COLLECT_FERTILIZER", "target": tuple(t.pos),
                        "args": [], "kind": "fallback_fert", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                assignment[best_u] = task
                targeted_positions.add(tuple(t.pos))

        # 2. Fallback: water any mature or unwatered crop
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_plant and not t.watered_today and tuple(t.pos) not in targeted_positions:
                best_u = min(unassigned_units, key=lambda u: abs(pos_by_idx[u][0] - t.x) + abs(pos_by_idx[u][1] - t.y))
                unassigned_units.remove(best_u)
                busy.add(best_u)
                task = {"priority": 10, "op": "WATER", "target": tuple(t.pos),
                        "args": [], "kind": "fallback_water", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                assignment[best_u] = task
                targeted_positions.add(tuple(t.pos))

        # 3. Fallback: dig any weed on unlocked land
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.kind == "WEED" and farm.quadrant_of(t.pos) in farm.unlocked and tuple(t.pos) not in targeted_positions:
                best_u = min(unassigned_units, key=lambda u: abs(pos_by_idx[u][0] - t.x) + abs(pos_by_idx[u][1] - t.y))
                unassigned_units.remove(best_u)
                busy.add(best_u)
                task = {"priority": 5, "op": "DIG", "target": tuple(t.pos),
                        "args": [], "kind": "fallback_dig", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                assignment[best_u] = task
                targeted_positions.add(tuple(t.pos))

    actions = {idx: ["PASS"] for idx in range(len(units))}
    for idx, task in assignment.items():
        actions[idx] = emit(task)

    # v5.9: Track utilization across all 24 hours of the day
    _record_turn_utilization(ctx, len(units), actions)

    # Bookkeeping: PLANT intents count as seed reservations whether or not the
    # unit is standing on the tile yet (seeds are consumed only on execution,
    # but the atomic all-or-nothing rule counts REQUESTS this turn).
    plant_intents = {}
    watered_now, harvested, fed_animals = [], [], []
    executed_plants = {}
    for task in assignment.values():
        if task["op"] == "PLANT":
            crop = task["args"][0] if task.get("args") else None
            if crop:
                plant_intents[crop] = plant_intents.get(crop, 0) + 1
                if task["unit_pos"] == tuple(task["target"]):
                    executed_plants[crop] = executed_plants.get(crop, 0) + 1
        elif task["op"] == "WATER":
            watered_now.append(task["target"])
        elif task["op"] == "HARVEST":
            harvested.append(task["target"])
        elif task["op"] == "FEED":
            fed_animals.append(task["target"])
    return {
        "actions": actions,
        "assignment": assignment,
        "plant_intents": plant_intents,
        "executed_plants": executed_plants,
        "watered_now": watered_now,
        "harvested": harvested,
        "fed": fed_animals,
        "deferred_place": [(t.get("args") or [None])[0] for t in deferred_place],
    }


def emit(task):
    """Move toward target or execute op when standing on it."""
    op = task["op"]
    target = task.get("target")
    pos = tuple(task.get("unit_pos", (4, 4)))

    if target is not None and pos != tuple(target):
        move = bfs_first_step(pos, tuple(target))
        if move is not None:
            return [move]
        # already adjacent-but-unreachable case shouldn't happen on open grid

    if op == "PICKUP":
        return ["PICKUP", *task.get("args", [])]
    if op == "PLACE":
        return ["PLACE", *task.get("args", [])]
    if task.get("args"):
        return [op, *task["args"]]
    return [op]


def estimate_daily_load(ctx):
    """Rough action-count needed today (used by hiring_manager)."""
    day = ctx["day"]
    load = 0
    for t in ctx["farm"].iter_tiles():
        if t.is_plant and not t.watered_today:
            load += 1
        if t.is_animal:
            load += 1 + (1 if t.fertilizer_available else 0)
            info = ANIMALS.get(t.animal)
            if info and (day + 1 - t.placed_day - info["first_yield_day"]) % info["interval"] == 0:
                load += 1  # production-day feed + harvest next morning
    seed_units = sum(ctx["private"].seeds.values())
    empty_unlocked = sum(
        1 for t in ctx["farm"].iter_tiles()
        if t.kind == "EMPTY" and ctx["farm"].quadrant_of(t.pos) in ctx["farm"].unlocked
    )
    load += min(seed_units, empty_unlocked)
    return load

# ===========================================================================
# END MODULE: execution/task_scheduler.py
# ===========================================================================

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






# ---------------------------------------------------------------------------
# Asset economics — imported from authoritative baked_economics artifact.
# ---------------------------------------------------------------------------
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
        buy_wheat = 0
        reserved_structure_tiles = []
        EFFECTIVE_ACTIONS_PER_UNIT = 12

        # v5.9: Fixed hiring schedule — no dynamic computation
        target_hands = get_target_hands(day)
        current_hands = len(farm.hands)
        hires = max(0, target_hands - current_hands)

        # v5.9: Animal targets from fixed scaling schedule
        target_geese, target_cows, target_sheep = get_animal_targets(target_hands)
        # Map targets to animal list
        fixed_targets = {"GOOSE": target_geese, "COW": target_cows, "SHEEP": target_sheep}

        # endgame: no new animals — just feed what we have
        if not is_endgame:
            # v5.9: Cash-flow guard — only buy animals if we can fund
            # mandatory hires for the next 3 days.
            future_hire_cost = sum(hire_total_cost(get_target_hands(d))
                                   for d in range(day, min(day + 3, 30)))
            cash_for_animals = max(0, ctx["farm"].money - future_hire_cost - self.reserve)
            
            # Labor capacity check: can the workforce handle more animals?
            ANIMAL_LABOR_PER_HEAD = 3
            current_load = estimate_daily_load(ctx)
            planned_units = 1 + target_hands
            current_capacity = planned_units * EFFECTIVE_ACTIONS_PER_UNIT
            spare_labor = max(0, current_capacity - current_load)

            # Tile reservation: keep minimum tiles for crops
            MIN_CROP_TILES_RESERVE = 5

            for animal in ANIMAL_LIST:
                target = fixed_targets.get(animal, 0)
                deficit_a = target - counts.get(animal, 0)
                if deficit_a <= 0:
                    continue
                info = ANIMALS[animal]
                econ = ANIMAL_ECONOMICS[animal]
                prod = info["product"]
                sale_days = list(range(info["first_yield_day"], 30, info["interval"]))
                e_price = _mean_over(self.fc, prod, sale_days)
                gross = econ["out30"] * e_price
                feed_cost = econ["feed30"] * 25.0
                if gross - feed_cost - info["cost"] <= 0:
                    continue
                if spare_labor < ANIMAL_LABOR_PER_HEAD:
                    continue

                # P0: Enforce Structure -> Animal dependency
                struct_kind = info["structure"]
                free_struct = [pos for pos, k in structures_empty.items()
                               if k == struct_kind]
                if free_struct:
                    # Empty structure exists on board -> safe to buy animal
                    if cash_for_animals >= info["cost"]:
                        buy_animal[animal] = buy_animal.get(animal, 0) + 1
                        cash_for_animals -= info["cost"]
                        del structures_empty[free_struct[0]]
                elif empty_tiles:
                    # No structure exists -> queue structure build first on authoritative empty tile
                    existing_structs = sum(1 for t in farm.iter_tiles() if t.kind == struct_kind) + len(reserved_structure_tiles)
                    target_structs = target if animal == "GOOSE" else (fixed_targets.get("COW", 0) + fixed_targets.get("SHEEP", 0))
                    if existing_structs < target_structs and len(reserved_structure_tiles) < 1 and len(empty_tiles) > MIN_CROP_TILES_RESERVE:
                        tile = empty_tiles.pop(0)
                        reserved_structure_tiles.append((tile, "BUILD_" + struct_kind))

        # single build_op per day: use the specific op for the reserved tile
        if reserved_structure_tiles:
            plan.build_op = reserved_structure_tiles[0][1]
            plan.build_queue = [t for t, _ in reserved_structure_tiles[:3]]

        # ---------------- crop queue on remaining tiles ----------------
        # endgame: no new planting — just harvest and sell
        plant_queue = []
        buy_seed = {}
        # ---- Budget prioritization (Fix 6) ----
        money = ctx["farm"].money
        hire_cost = hire_total_cost(hires)

        n_extra = len(farm.unlocked) - 1
        land_cost = 0
        if not is_endgame and n_extra < len(LAND_ORDER):
            land_price = LAND_PRICES[n_extra]
            if money >= land_price + self.reserve + 200:
                land_cost = land_price

        animal_cost = sum(ANIMALS[a]["cost"] * k for a, k in buy_animal.items())
        
        # Feed wheat buffer needed for existing + newly bought animals
        # In early game (day <= 5), ensure at least 5 wheat buffer so animals survive until farm wheat matures
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
        seed_budget = max(0.0, available_before_seeds - wheat_feed_cost)
        remaining_money = seed_budget

        seeds = dict(private.seeds)
        if not is_endgame:

            # ---- v5.9: Plant ALL empty tiles with best crops ----
            # Spec: "Day 0: PLANT all available tiles with wheat AND WATER
            # every planted tile the same day."
            # Fill every empty tile with the highest-scoring crop.
            
            # Phase 2a: Wheat planting
            # Day 0: Plant all available tiles with wheat (backbone + prevents weed trap)
            # Days > 0: Plant wheat up to target buffer, leaving remaining tiles for cash crops
            wheat_available = seeds.get("WHEAT", 0)
            if day == 0:
                wheat_to_plant = len(empty_tiles)
                if wheat_to_plant > wheat_available:
                    needed_seeds = wheat_to_plant - wheat_available
                    buy_seed["WHEAT"] = buy_seed.get("WHEAT", 0) + needed_seeds
                    remaining_money = max(0.0, remaining_money - needed_seeds * CROPS["WHEAT"]["seed"])
                    seeds["WHEAT"] = wheat_to_plant
            else:
                existing_wheat = sum(1 for t in farm.iter_tiles() if t.is_plant and t.crop == "WHEAT")
                quadrant_wheat_target = max(6, len(farm.unlocked) * 5)
                wheat_cap = min(len(empty_tiles) // 2 + 2, quadrant_wheat_target)
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

            # Phase 2b: Fill remaining empty tiles with best-scoring crops
            # Only plant if we have seeds or money to buy them
            for pos in list(empty_tiles):
                best_score, best_crop = -1e9, None
                for crop in CROPS:
                    if not _crop_allowed_today(crop, day):
                        continue
                    if planned.get(crop, 0) >= CROP_TILE_CAPS.get(crop, 99):
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

        # ---- v5.9: Fixed land expansion schedule ----
        buy_land = False
        if not is_endgame:
            n_extra_unlocked = len(farm.unlocked) - 1
            next_quadrant = n_extra_unlocked + 2  # quadrants are 1-indexed: NW=1, NE=2, SW=3, SE=4

            # Hard block: NEVER buy quadrant 4
            if next_quadrant in QUADRANT_HARD_BLOCK:
                pass  # blocked forever
            elif next_quadrant in QUADRANT_UNLOCK_DAYS:
                unlock_day = QUADRANT_UNLOCK_DAYS[next_quadrant]
                money_threshold = QUADRANT_MONEY_THRESHOLDS[next_quadrant]
                if day >= unlock_day and ctx["farm"].money >= money_threshold:
                    buy_land = True
                    remaining_money -= LAND_PRICES[n_extra_unlocked]

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
            held = inv_hold.get(animal)
            if held:
                place_queue.append({"op": "PLACE", "target": sorted(free)[0],
                                    "args": [animal]})
            elif private.shed.get(animal, 0) > 0:
                place_queue.append({"op": "PICKUP",
                                    "target": (4, 4), "args": [animal]})
            break   # one species per day keeps the queue focused

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

# ===========================================================================
# END MODULE: strategy/macro_planner.py
# ===========================================================================

"""W-market 1/3: MacroPlanner intents -> valid engine market orders.

Engine semantics honored (kaggriculture.py):
  - max `maxMarketOrdersPerTurn` (10) orders; extras silently dropped
  - HIRE hires exactly ONE hand per order entry, cost fib(hires_today)
  - BUY_LAND costs LAND_PRICES[len(unlocked)-1]; no-op if locked none left
  - BUY_SEED / BUY_ANIMAL: fixed per-unit cost; animals land in the SHED
    and both obey shedCapacity at commit time
  - BUY_PRODUCT only WHEAT/FERTILIZER; quoted at post-buy inventory so the
    effective price drifts UP while buying -> we budget with a buffer
  - any failed commit aborts that order; ordering the queue by priority
    therefore acts as a graceful degradation mechanism

Budget rule: total estimated spend <= money - reserve. Tiers are filled in
priority order and count-based tiers are clamped to what remains affordable.
"""






def _fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def hire_total_cost(k_hands, mult=1):
    """Coins for k hires made today (fib(0)+...+fib(k-1))."""
    return sum(_fib(i) for i in range(k_hands)) * mult


# Priority tiers (lower = executed earlier when order slots / cash run short).
TIER_LAND = 0
TIER_FEED_WHEAT = 1
TIER_SEEDS = 2
TIER_ANIMALS = 3
TIER_HIRES = 4


class OrderBuilder:
    def __init__(self, money_reserve=MONEY_RESERVE_DEFAULT):
        self.reserve = money_reserve

    # ------------------------------------------------------------------
    def build(self, ctx, intents):
        """intents: MacroPlan.intents dict. Returns (orders, ledger).
        
        v5.9: Hires are NON-NEGOTIABLE. They get first claim on money,
        regardless of budget/reserve. Seeds, animals, land are bought
        only with what remains after hire cost.
        """
        farm = ctx["farm"]
        money = float(farm.money)
        budget = max(0.0, money - self.reserve)

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}
        wheat_px = market_price("WHEAT", inv.get("WHEAT", 10000))
        shed_room = max(0, 100 - sum(ctx["private"].shed.values()))

        ledger = {"budget": round(budget, 2), "queued": [],
                  "dropped": [], "spent_estimate": 0.0}

        # ---- v5.9: Hires get absolute priority (full money) -----------
        tiers = []
        k = int(intents.get("hire", 0))
        hire_cost = 0.0
        if k > 0:
            hire_cost = float(hire_total_cost(k))
            tiers.append((TIER_HIRES, "hire",
                          {"count": k}, hire_cost))

        # ---- Remaining budget after mandatory hires (protecting reserve) ----
        post_hire_budget = max(0.0, budget - hire_cost)

        # ---- tier 1: seeds -------------------------------------------
        for crop, n in sorted(intents.get("buy_seed", {}).items()):
            n = int(n)
            if n > 0 and crop in CROPS:
                unit = CROPS[crop]["seed"]
                tiers.append((TIER_SEEDS, "seed",
                              {"crop": crop, "n": n}, unit * n))

        # ---- tier 2: feed wheat --------------------------------------
        w = int(intents.get("buy_wheat", 0))
        if w > 0:
            est = math_ceil(wheat_px * WHEAT_BUY_PRICE_BUFFER) * w
            tiers.append((TIER_FEED_WHEAT, "wheat", {"n": w}, est))

        # ---- tier 3: animals -----------------------------------------
        for animal, k in sorted(intents.get("buy_animal", {}).items()):
            k = int(k)
            if k > 0 and animal in ANIMALS:
                struct_type = ANIMALS[animal]["structure"]
                free_structures = sum(
                    1 for t in farm.iter_tiles()
                    if t.kind == struct_type and not t.is_animal
                )
                matching_animals = [a for a, info in ANIMALS.items() if info["structure"] == struct_type]
                animals_in_shed = sum(int(ctx["private"].shed.get(a, 0)) for a in matching_animals) if ctx.get("private") else 0
                max_buyable = max(0, free_structures - animals_in_shed)
                room_limited = min(k, max_buyable, shed_room)
                if room_limited <= 0:
                    ledger["dropped"].append({"kind": "animal",
                                              "animal": animal,
                                              "reason": "no_empty_structure" if max_buyable <= 0 else "shed_full"})
                    continue
                unit = ANIMALS[animal]["cost"]
                tiers.append((TIER_ANIMALS, "animal",
                              {"animal": animal, "n": room_limited},
                              unit * room_limited))

        # ---- tier 4: land --------------------------------------------
        n_extra = len(farm.unlocked) - 1
        land_price = None
        if intents.get("buy_land") and n_extra < len(LAND_ORDER):
            land_price = LAND_PRICES[n_extra]
            tiers.append((TIER_LAND, "land", {}, float(land_price)))

        # ---- fill tiers: hires first (non-negotiable), then rest ------
        spent = 0.0
        kept = []
        for tier, kind, payload, est in sorted(tiers, key=lambda t: t[0]):
            if kind == "hire":
                # Hires use full money — always fit
                kept.append((tier, kind, payload, est))
                spent += est
                continue
            # Everything else uses post-hire budget
            remaining = max(0.0, post_hire_budget - (spent - hire_cost))
            if est <= remaining + 1e-9:
                kept.append((tier, kind, payload, est))
                spent += est
                continue
            # partial trim for count-based kinds
            if kind == "seed":
                unit = CROPS[payload["crop"]]["seed"]
                n_max = int(remaining // unit)
                if n_max > 0:
                    kept.append((tier, "seed",
                                 {"crop": payload["crop"], "n": n_max},
                                 unit * n_max))
                    spent += unit * n_max
                    ledger["dropped"].append(
                        {"kind": "seed", "crop": payload["crop"],
                         "trimmed_from": payload["n"], "to": n_max})
                else:
                    ledger["dropped"].append({"kind": "seed",
                                              "crop": payload["crop"],
                                              "reason": "budget"})
            elif kind == "animal":
                unit = ANIMALS[payload["animal"]]["cost"]
                n_max = int(remaining // unit)
                if n_max > 0:
                    kept.append((tier, "animal",
                                 {"animal": payload["animal"], "n": n_max},
                                 unit * n_max))
                    spent += unit * n_max
                    ledger["dropped"].append(
                        {"kind": "animal", "animal": payload["animal"],
                         "trimmed_from": payload["n"], "to": n_max})
                else:
                    ledger["dropped"].append({"kind": "animal",
                                              "animal": payload["animal"],
                                              "reason": "budget"})
            elif kind == "wheat":
                unit_px = math_ceil(wheat_px * WHEAT_BUY_PRICE_BUFFER)
                n_max = int(remaining // unit_px)
                if n_max > 0:
                    kept.append((tier, "wheat", {"n": n_max},
                                 unit_px * n_max))
                    spent += unit_px * n_max
                    ledger["dropped"].append({"kind": "wheat",
                                               "trimmed_from": payload["n"],
                                               "to": n_max})
                else:
                    ledger["dropped"].append({"kind": "wheat",
                                              "reason": "budget"})
            elif kind == "land":
                ledger["dropped"].append({"kind": "land",
                                          "reason": "budget"})

        # ---- emit engine-format orders, honoring the 10-order cap -----
        orders = []
        queued = {"hire": 0, "seed": {}, "animal": {}, "wheat": 0, "land": False}
        slots = MAX_MARKET_ORDERS

        def take(slot_item):
            nonlocal slots
            if slots <= 0:
                return False
            slots -= 1
            return True

        for tier, kind, payload, est in sorted(kept, key=lambda t: t[0]):
            if kind == "hire":
                emitted = 0
                while payload["count"] - emitted > 0 and slots > 0:
                    orders.append(["HIRE"])
                    slots -= 1
                    emitted += 1
                queued["hire"] = emitted
                if emitted < payload["count"]:
                    ledger["dropped"].append({"kind": "hire_slots"})
            elif kind == "seed":
                if take(None):
                    orders.append(["BUY_SEED", payload["crop"],
                                   int(payload["n"])])
                    queued["seed"][payload["crop"]] = int(payload["n"])
                else:
                    ledger["dropped"].append({"kind": "seed_slots",
                                              "crop": payload["crop"]})
            elif kind == "wheat":
                if take(None):
                    orders.append(["BUY_PRODUCT", "WHEAT", int(payload["n"])])
                    queued["wheat"] = int(payload["n"])
                else:
                    ledger["dropped"].append({"kind": "wheat_slots"})
            elif kind == "animal":
                if take(None):
                    orders.append(["BUY_ANIMAL", payload["animal"],
                                   int(payload["n"])])
                    queued["animal"][payload["animal"]] = int(payload["n"])
                else:
                    ledger["dropped"].append({"kind": "animal_slots",
                                              "animal": payload["animal"]})
            elif kind == "land":
                next_quadrant = len(farm.unlocked) + 1
                assert next_quadrant != 4, "Quadrant 4 (SE) is permanently hard-blocked and must NEVER be purchased!"
                if take(None):
                    orders.append(["BUY_LAND"])
                    queued["land"] = True
                else:
                    ledger["dropped"].append({"kind": "land_slots"})

        ledger["queued"] = queued
        ledger["orders"] = [list(o) for o in orders]
        ledger["spent_estimate"] = round(spent, 2)
        return orders, ledger


def math_ceil(x):
    import math
    return int(math.ceil(x))


def land_price_for(unlocked_count):
    """Price of the NEXT quadrant given number of unlocked quadrants."""
    n_extra = unlocked_count - 1
    if n_extra >= len(LAND_ORDER):
        return None
    return LAND_PRICES[n_extra]


if __name__ == "__main__":
    print("module provides OrderBuilder; see tests for usage")

# ===========================================================================
# END MODULE: market/order_builder.py
# ===========================================================================

"""W-market 2/3: Sell-side decision layer.

Consumes live observation + PriceForecast (W1) + price_math (engine-exact
curves) and decides WHICH shed stock to sell, HOW MUCH per product, and WHEN
(sell windows, floor holds, drip slices).

Decision rules (in order):
  1. WINDOW: sells only on hours t % 4 == 1 — the engine's town shops drain
     at step % 4 == 0 and prices refresh right after, so hour≡1 quotes are
     post-drain boosted. Endgame day 29 dumps in every window.
  2. FLOOR HOLD: premium goods quoted at $1 are held while enough season
     remains for town drain to lift them (selling at $1 still books revenue
     but freezes inventory — holding is free upside).
  3. CARRY CHECK: hold a product if E[P | day+horizon] exceeds today's spot
     by more than MIN_CARRY_GAIN AND the shed is not under soft-cap pressure.
  4. DRIP SLICE: quantity = largest slice whose LAST unit still realizes
     >= keep_frac * spot (price_math.inventory_for_price_at_least), clamped
     by shed stock and by wheat reserved for animal feed.
  5. SLOTS: sells take at most SELL_SLOT_SHARE of the order cap; candidates
     ranked by shed-share urgency (round-robin emerges as leaders empty).

Self-competition awareness: drip sizing is computed against LIVE market
inventory, which already includes this farm's earlier same-day sales, so
slices automatically shrink as we move our own curve. The reference E[P|day]
is used only for carry/hold comparisons, never as an average sell price.
"""




SELLABLE = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY",
            "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")


class MarketBrain:
    def __init__(self, forecast):
        self.fc = forecast

    # ------------------------------------------------------------------
    def sell_orders(self, ctx, max_slots=None, opp_advice=None):
        """Returns (orders, details). orders: [["SELL", prod, qty], ...].

        v5.9: Sell every hour (not just t%4==1) to fund mandatory hires.
        Batch sizes follow spec:
          Days 0-5:  10-20 units per product
          Days 6-8:  5-10 units
          Days 9+:   3-5 units
        Carry/floor holds are relaxed — cash flow > price optimization.
        """
        if max_slots is None:
            max_slots = int(MAX_MARKET_ORDERS * SELL_SLOT_SHARE)
        day, hour = ctx["day"], ctx["hour"]
        days_left = 29 - day
        endgame = day >= ENDGAME_START_DAY

        shed = ctx["private"].shed
        animals = sum(1 for t in ctx["farm"].iter_tiles() if t.is_animal)
        reserved_wheat = 0 if endgame else animals * FEED_WHEAT_BUFFER_DAYS
        shed_total = sum(shed.get(p, 0) for p in SELLABLE)
        pressure = shed_total >= SHED_SOFT_CAP

        # v5.9: Sell every hour (cash flow for hires) except hour 0 (purchases)
        if hour == 0 and not endgame:
            return [], {"reason": "hour0_purchases"}

        # Phase 6: extract opp_advice sets for fast lookup
        preempt_set = set(opp_advice.preempt_sell) if opp_advice else set()
        delay_set = set(opp_advice.delay_sell) if opp_advice else set()

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}
        candidates = []
        
        # v5.9: Spec batch sizes per phase
        if day <= 5:
            batch_target = 15  # sell 10-20 units
        elif day <= 8:
            batch_target = 7   # sell 5-10 units
        else:
            batch_target = 4   # sell 3-5 units
        
        for prod in SELLABLE:
            if prod in delay_set and not endgame:
                continue
            stock = int(shed.get(prod, 0))
            if stock <= 0:
                continue
            if prod == "WHEAT":
                stock = max(0, stock - reserved_wheat)
                if stock <= 0:
                    continue
            spot = market_price(prod, inv.get(prod, 10000))
            
            # v5.9: Never hold at floor — sell everything for cash flow
            if spot <= 1:
                qty = stock if endgame else min(stock, batch_target)
                if qty > 0:
                    candidates.append({
                        "product": prod, "qty": int(qty), "spot": spot,
                        "avg_est": spot, "reason": "floor_sell",
                        "urgency": 0.5,
                    })
                continue

            # v5.9: In endgame/aggressive mode, dump entire stock; otherwise sell at spec batch size
            aggressive = endgame or days_left <= ENDGAME_RISK_DAYS or pressure
            qty = stock if (endgame or days_left <= 2) else min(stock, batch_target)
            
            if qty <= 0:
                continue

            avg_est = total_revenue_estimate(prod, inv.get(prod, 10000),
                                             qty) / qty
            reason = "spec_batch_sell"
            urgency = stock / (shed_total or 1)

            # --- Phase 6: preempt sell urgency boost ----------------
            if prod in preempt_set:
                urgency = max(urgency, 0.99)
                reason = "preempt_dump"

            candidates.append({
                "product": prod, "qty": int(qty), "spot": spot,
                "avg_est": round(avg_est, 2), "reason": reason,
                "urgency": urgency,
            })

        candidates.sort(key=lambda c: -c["urgency"])
        chosen = candidates[:max_slots]
        orders = [["SELL", c["product"], c["qty"]] for c in chosen]
        return orders, {"candidates": candidates, "days_left": days_left,
                        "endgame": endgame, "pressure": pressure}

    # ------------------------------------------------------------------
    def _drip_budget(self, prod, current_inv, keep_frac, spot):
        threshold = max(2, int(spot * keep_frac))
        limit = inventory_for_price_at_least(prod, threshold)
        budget = int(limit - float(current_inv))
        return max(0, budget)

    def _is_sell_hour(self, day, hour):
        return hour in SELL_HOUR_SET

    def _reason(self, prod, spot, carry, aggressive, pressure):
        if aggressive:
            return "endgame_dump" if spot <= 1 else "aggressive_slice"
        if pressure:
            return "shed_pressure"
        return "carry_fail" if carry <= MIN_CARRY_GAIN else "carry_hold"

    # ------------------------------------------------------------------
    @staticmethod
    def compose(purchase_orders, sell_orders, cap=MAX_MARKET_ORDERS,
                purchases_first=False):
        """Merge purchase + sell queues under the engine's per-turn cap.

        Default priority: SELLS first (they book revenue and free shed space;
        missing a buy costs one turn, but overflowing the shed destroys
        goods). Pass purchases_first=True for the hour-0 hire/seed block.
        """
        first, second = ((purchase_orders, sell_orders) if purchases_first
                         else (sell_orders, purchase_orders))
        out = [list(o) for o in first][:cap]
        out += [list(o) for o in second][:cap - len(out)]
        return out

# ===========================================================================
# END MODULE: market/market_brain.py
# ===========================================================================

"""W-market 3/3: Endgame liquidation policy.

Orchestrates days >= ENDGAME_START_DAY:
  - classifies every shed product as HOLD-FOR-RECOVERY or DUMP-NOW using the
    validated forecast (E[P|29] uplift vs today, floor probability at 29)
  - emits aggressive sell slices via market_brain (round-robin across
    products so no single glut curve eats the whole order cap)
  - harvesting is left to task_scheduler, which already prioritizes any tile
    with yield_units > 0; this module only guarantees the RESULTING stock
    gets sold before day 30 (unsold inventory is worth zero at scoring)

No crop-specific logic: classification is purely price-distribution driven.
"""





class EndgameLiquidator:
    def __init__(self, forecast, brain=None):
        self.fc = forecast
        self.brain = brain or MarketBrain(forecast)

    # ------------------------------------------------------------------
    def should_liquidate_now(self, product, day):
        """True when waiting for day-29 prices no longer pays.

        Rule: dump if the expected uplift from holding to day 29 is under
        2% OR if there is a material chance the price sits at the $1 floor
        on day 29 (recovery already failed).
        """
        spot_day = min(day, 29)
        e_now = self.fc.expected_price(product, spot_day)
        e_end = self.fc.expected_price(product, 29)
        if e_now <= 0:
            return True
        uplift = e_end / e_now - 1.0
        p_floor_end = self.fc.prob_floor(product, 29)
        return uplift < 0.02 or p_floor_end > 0.30

    # ------------------------------------------------------------------
    def plan(self, ctx, max_slots=MAX_MARKET_ORDERS, opp_advice=None):
        """Aggressive endgame sells for THIS turn.

        Uses MarketBrain in its naturally aggressive endgame mode and then
        tops up: any product with remaining stock that was skipped due to
        drip budgeting gets a follow-up slice on later windows automatically
        (stock shrinks monotonically), so round-robin coverage emerges.
        """
        orders, details = self.brain.sell_orders(ctx, max_slots=max_slots,
                                                 opp_advice=opp_advice)
        details["liquidated_products"] = sorted(
            c["product"] for c in details.get("candidates", []))
        return orders, details

    # ------------------------------------------------------------------
    def harvest_priorities(self, ctx):
        """Tiles whose yield should leave the farm TODAY (scheduler already
        emits HARVEST for these; exposed for tests/visibility)."""
        out = []
        for t in ctx["farm"].iter_tiles():
            if t.is_plant and t.yield_units > 0:
                out.append({"pos": t.pos, "crop": t.crop,
                            "units": t.yield_units})
            elif t.is_animal and t.yield_units > 0:
                out.append({"pos": t.pos, "crop": t.animal,
                            "units": t.yield_units})
        return out

# ===========================================================================
# END MODULE: strategy/endgame_liquidator.py
# ===========================================================================

"""
Kaggriculture Master Agent — Closed-Loop Adaptive Architecture

Architecture Chain:
  obs -> parse_observation -> PriceForecast (W1) -> MacroPlanner (W2)
      -> TaskScheduler (unit actions)
      + OrderBuilder (purchase orders) + MarketBrain (sell orders) + EndgameLiquidator
      -> Action Dict {"farmer": ..., "hands": ..., "market": ...}

  Phase 6: Opponent Modeling pipeline
      obs -> get_state() -> OpponentModel -> OpponentAdvisor -> MacroPlanner + MarketBrain

Submission Rule Compliance:
  - The last 'def' in this file is the agent entry point: def agent(obs, config=None)
"""







PASS_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}

# Singleton / lazy-loaded instances
_FC = None
_PLANNER = None
_BUILDER = None
_BRAIN = None
_LIQUIDATOR = None

# Persistent opponent modeling state (survives across turns within one process)
_prev_opp_snapshot = None
_estimated_shed = None


def _get_components():
    global _FC, _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR
    if _FC is None:
        _FC = PriceForecast.load()
        _PLANNER = MacroPlanner(_FC)
        _BUILDER = OrderBuilder()
        _BRAIN = MarketBrain(_FC)
        _LIQUIDATOR = EndgameLiquidator(_FC, _BRAIN)
    return _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR


def _build_opp_advice(ctx, mem):
    """Build OpponentAdvice from current observation and persistent memory.

    Returns OpponentAdvice (always safe — empty advice on any missing data).
    """
    try:
        opp_farm = ctx.get("opponent_farm")
        if opp_farm is None:
            return OpponentAdvice()

        # Phase 1: snapshot and detect deltas
        global _prev_opp_snapshot, _estimated_shed
        new_snap = snapshot_opponent_farm(opp_farm)
        deltas = detect_tile_deltas(opp_farm, _prev_opp_snapshot)
        _prev_opp_snapshot = new_snap

        # Phase 2: forecast production
        forecast = forecast_opponent_production(opp_farm, ctx["day"])

        # Phase 3: update shed estimate
        opp_animals = sum(1 for t in opp_farm.iter_tiles() if t.is_animal)
        opp_sales = mem.get("opp_sales_inferred", {})
        _estimated_shed = update_opponent_shed_estimate(
            _estimated_shed, deltas, opp_sales,
            opp_animals, ctx["day"], ctx["hour"],
        )

        # Phase 3: sell probabilities
        opp_state_for_probs = {
            "estimated_shed": _estimated_shed,
            "sell_probs": {},
            "opp_sales_inferred": opp_sales,
            "shed_pressure": sum(_estimated_shed.values()) / 100.0,
            "forecast": forecast,
            "commitments": summarize_opponent_commitments(opp_farm),
            "animal_counts": {t.animal: 1 for t in opp_farm.iter_tiles()
                              if t.is_animal},
        }
        sell_probs = compute_opponent_sell_probabilities(
            opp_farm, _estimated_shed, ctx, mem,
        )
        opp_state_for_probs["sell_probs"] = sell_probs

        # Phase 5: build advice
        town_obj = ctx.get("town")
        unlocked_shops = getattr(town_obj, "unlocked_shops", None)
        if unlocked_shops is None and isinstance(town_obj, dict):
            unlocked_shops = town_obj.get("unlocked_shops", [])
        boosts = demand_boosts(unlocked_shops or [])
        advice = build_opponent_advice(
            opp_state_for_probs, ctx, forecast, boosts=boosts,
        )
        return advice
    except Exception:
        # Never let opponent modeling crash the main agent
        return OpponentAdvice()


def _agent_decision(obs: Dict[str, Any]) -> Dict[str, Any]:
    # Phase 6: use get_state for persistent memory + episode detection
    ctx, mem = get_state(obs)
    if ctx is None:
        return dict(PASS_ACTION)

    planner, builder, brain, liquidator = _get_components()

    # v5.9: Reset daily log at start of day 0
    if ctx["day"] == 0 and ctx["hour"] == 0:
        reset_daily_log()

    # Dynamic shop boosts from observed town unlocks
    known_shops = obs.get("town", {}).get("unlocked_shops", [])
    boosts = demand_boosts(known_shops)

    # Phase 6: build opponent advice
    opp_advice = _build_opp_advice(ctx, mem)

    # 1. Macro strategic planning (with opponent supply/counter-pick)
    plan = planner.build(ctx, boosts=boosts, opp_advice=opp_advice)

    # v5.9: Hard guard — NEVER allow quadrant 4 purchase
    if plan.intents.get("buy_land"):
        n_extra = len(ctx["farm"].unlocked) - 1
        next_q = n_extra + 2
        if next_q in QUADRANT_HARD_BLOCK:
            plan.intents["buy_land"] = False  # force block

    # 2. Execution layer: unit tasks and greedy spatial assignment
    tasks = build_tasks(ctx, plan)
    asg = assign_tasks(tasks, ctx)

    # 3. Market layer: purchase intent compilation (morning market at hour 0 + deferred hires at hour 1)
    purchase_orders = []
    if ctx["hour"] == 0:
        purchase_orders, _ledger = builder.build(ctx, plan.intents)
    elif ctx["hour"] == 1:
        # Check if any target hires from today's plan were deferred from Hour 0
        target_h = get_target_hands(ctx["day"])
        hires_so_far = ctx["farm"].hires_today
        hires_needed = max(0, target_h - hires_so_far)
        if hires_needed > 0:
            for _ in range(min(hires_needed, 10)):
                purchase_orders.append(["HIRE"])
        
    if ctx["day"] >= 28:
        sell_orders, _d = liquidator.plan(ctx, opp_advice=opp_advice)
    else:
        sell_orders, _d = brain.sell_orders(ctx, opp_advice=opp_advice)

    market = MarketBrain.compose(
        purchase_orders, sell_orders,
        purchases_first=(ctx["hour"] in (0, 1))
    )

    # Phase 6: record our sales for drain ledger accuracy
    for order in market:
        if order[0] == "SELL":
            record_our_sale(order[1], order[2])

    # 4. Action dict assembly
    n_units = 1 + len(ctx["farm"].hands)
    return {
        "farmer": list(asg["actions"].get(0, ["PASS"])),
        "hands": [list(asg["actions"].get(i, ["PASS"])) for i in range(1, n_units)],
        "market": market,
    }


# ==============================================================================
# KAGGLE ENTRY POINT (LAST 'def')
# ==============================================================================
def agent(obs: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Official competition entry point with top-level fail-safe."""
    try:
        return _agent_decision(obs)
    except Exception:
        return dict(PASS_ACTION)

# ===========================================================================
# END MODULE: main.py
# ===========================================================================
