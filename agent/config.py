"""Tunable hyperparameters + engine-constant mirror (latest kaggriculture.py).

v5.9: Fixed hiring schedule + action-budget allocator.
All engine facts here are mirrored from the installed kaggle_environments
kaggriculture plugin (CROPS / ANIMALS / MARKET_PARAMS / SHOPS / timings).
"""
import math
import sys
from typing import Tuple, Dict, Optional, Any, List, Set

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
# Harvest-realization logistics. Normal batching sits just above routine harvest;
# pressure delivery stays below decay harvest; final-day delivery outranks new harvests.
PRIORITY_PRODUCT_DELIVERY = 68
PRIORITY_PRODUCT_DELIVERY_PRESSURE = 88
PRIORITY_ENDGAME_PRODUCT_DELIVERY = 98
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

# Point 2 — Feed/Herd Feasibility Rollout Mode
# Supported modes: "off", "shadow", "herd_plan", "live"
POINT2_FEED_MODE = "shadow"
FEED_OPERATIONAL_HORIZON_DAYS = FEED_WHEAT_BUFFER_DAYS

# Point 2 Day-0 Early Livestock Bootstrap Experiment
# Supported arms: "none", "ArmB", "ArmC", "ArmD", "ArmE" (or "B", "C", "D", "E")
BOOTSTRAP_LIVESTOCK_ARM = "none"

BOOTSTRAP_SEQUENCES = {
    "none": [],
    "A": [],
    "ArmA": [],
    "B": ["COW", "COW"],
    "ArmB": ["COW", "COW"],
    "2c": ["COW", "COW"],
    "C": ["COW", "COW", "SHEEP"],
    "ArmC": ["COW", "COW", "SHEEP"],
    "2c_1s": ["COW", "COW", "SHEEP"],
    "D": ["COW", "COW", "SHEEP", "SHEEP"],
    "ArmD": ["COW", "COW", "SHEEP", "SHEEP"],
    "2c_2s": ["COW", "COW", "SHEEP", "SHEEP"],
    "E": ["COW", "COW", "COW"],
    "ArmE": ["COW", "COW", "COW"],
    "3c": ["COW", "COW", "COW"],
}

def get_bootstrap_target_sequence(arm: str = None) -> list:
    """Return target candidate sequence for the active Day-0 bootstrap arm."""
    if arm is None:
        arm = BOOTSTRAP_LIVESTOCK_ARM
    return list(BOOTSTRAP_SEQUENCES.get(arm, []))

def get_point2_feed_mode() -> str:
    """Return the active Point-2 feed/herd sustainability rollout mode."""
    return POINT2_FEED_MODE

# Point 2 Late-Housing Continuation Experiment
# Strictly one candidate -> one pasture -> wait for completion -> then buy (Days 12-13)
ONE_AT_A_TIME_LATE_HOUSING_ENABLED: bool = False

def get_one_at_a_time_late_housing_enabled() -> bool:
    """Return whether one-at-a-time late housing continuation is active."""
    return ONE_AT_A_TIME_LATE_HOUSING_ENABLED

# Point 2 Pre-NE Capital Admission Policy Experiment
# Supported modes: "off", "ne_first", "ne_escrow"
POINT2_PRE_NE_CAPITAL_MODE: str = "off"

def get_point2_pre_ne_capital_mode() -> str:
    """Return the active Point-2 Pre-NE capital admission policy mode."""
    return POINT2_PRE_NE_CAPITAL_MODE


# Phase knobs
PHASE1_WHEAT_TILES = 8            # NW wheat for day-4 cash + animal feed (Leader heuristic)
PHASE1_MELON_TILES_NW = 12        # NW melons for day-10 cash surge (Leader springboard)
PHASE1_GEESE_DAY0_2 = 0            # Zero Geese policy: geese produce low-margin down, zero fertilizer
MELON_PLANT_LAST_DAY_FERT = 17    # last planting that still harvests by 29
MELON_PLANT_LAST_DAY = 19

# Stage 8B Phase 1E: C2 Adaptive Zonal Dispatch
C2_MAX_SPILLOVER_DIST = 12         # Max Manhattan distance allowed for cross-quadrant spillover
C2_SPILLOVER_PRIORITY_FLOOR = 20   # Minimum task priority eligible for cross-quadrant dispatch

# Stage 8B Phase 1F: C6 Clustered Dispatch / Logistics Efficiency
C6_CLUSTER_RADIUS = 1              # Manhattan radius to qualify as adjacent/clustered task
C6_CLUSTER_BONUS = 2               # Distance discount for adjacent tasks; double discount for co-located tasks (d=0)
C6_PRIORITY_BAND = 20              # Compare routine work with nearby service tasks
C6_TRAVEL_WEIGHT = 3               # Charge priority points for each movement turn

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
    2: 3,    # Quadrant 2 (NE): buy on days 3-6 (Leader heuristic: cash >= 1200 on D6, 1400 on D3-5)
    3: 9,    # Quadrant 3 (SW): buy on day 9 (pre-buy day 8)
}
QUADRANT_MONEY_THRESHOLDS = {
    2: 1400,  # Need >= $1,400 to buy Q2 on D3-5 ($1,000 land + $400 seed/ops float)
    3: 2204,  # Need >= $2,204 to buy Q3 ($2,000 land + $150 escrow + $54 hires)
}
NE_EARLY_UNLOCK_MAX_DAY = 6
NE_EARLY_UNLOCK_THRESHOLD_DAY3_5 = 1400
NE_EARLY_UNLOCK_THRESHOLD_DAY6 = 1200
QUADRANT_HARD_BLOCK = {4}  # Production default: SE (4) hard-blocked; SW (3) controlled via experiment arm


def get_quadrant_hard_block() -> set:
    """Return the set of hard-blocked quadrant indices."""
    return set(QUADRANT_HARD_BLOCK)


def set_quadrant_hard_block(blocks) -> None:
    """Set the hard-blocked quadrant indices and sync loaded modules."""
    global QUADRANT_HARD_BLOCK
    QUADRANT_HARD_BLOCK = set(blocks)
    for mod_name in (
        "agent.strategy.expansion_planner", "strategy.expansion_planner",
        "agent.strategy.macro_planner", "strategy.macro_planner",
        "agent.main", "main",
    ):
        if mod_name in sys.modules:
            try:
                setattr(sys.modules[mod_name], "QUADRANT_HARD_BLOCK", set(blocks))
            except Exception:
                pass


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
EARLY_PASTURE_TILES = [(3, 4), (2, 4)]  # NW fallow tiles adjacent to shed for early livestock bootstrap

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

def get_strawberry_cap(day, strawberry_eligible=False, land_purchased=None):
    """Time-varying strawberry cap: 16 → 18 → 20 (Day 13 only) → 0.

    Rationale:
    - Day 0-8: Expanding (16) — early season in NW/NE
    - Day 9-12: Aggressive (18) — SW expanding production
    - Day 13: Maximum (20) — last day to plant strawberry (deadline)
    - Day 14+: Zero (0) — deadline passed, no new strawberry planting
    """
    eligible = strawberry_eligible if land_purchased is None else land_purchased
    if not eligible:
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
DEFAULT_ANIMAL_SCALING = {
    4:  (0, 2, 2),    # Days 0-5: 2 cows + 2 sheep (leader opening)
    8:  (0, 4, 4),    # Days 6-8: 4 cows + 4 sheep = 8 animals
    10: (0, 5, 8),    # Day 9: 5 cows + 8 sheep = 13 animals
    12: (0, 6, 12),   # Days 10-29: 6 cows + 12 sheep = 18 animals
}
ANIMAL_SCALING = dict(DEFAULT_ANIMAL_SCALING)

DEFAULT_TARGET_COWS = 6
DEFAULT_TARGET_SHEEP = 12
DEFAULT_HERD_CAP = 20
DEFAULT_COW_CAP = 19
DEFAULT_SHEEP_CAP = 12

LIVESTOCK_OVERRIDE_ENABLED = False
ACTIVE_TARGET_COWS = DEFAULT_TARGET_COWS
ACTIVE_TARGET_SHEEP = DEFAULT_TARGET_SHEEP
ACTIVE_COW_CAP = DEFAULT_COW_CAP
ACTIVE_SHEEP_CAP = DEFAULT_SHEEP_CAP
ACTIVE_HERD_CAP = DEFAULT_HERD_CAP

DYNAMIC_SW_CROPS_ENABLED = False
STRATEGIC_SW_OWNERSHIP_ENABLED = False


def get_active_livestock_targets() -> Tuple[int, int, int]:
    """Authoritative runtime getter for target animal counts (geese, cows, sheep)."""
    if not LIVESTOCK_OVERRIDE_ENABLED:
        return (TARGET_GEESE, DEFAULT_TARGET_COWS, DEFAULT_TARGET_SHEEP)
    return (TARGET_GEESE, ACTIVE_TARGET_COWS, ACTIVE_TARGET_SHEEP)


def get_active_livestock_caps() -> Dict[str, int]:
    """Authoritative runtime getter for species caps."""
    if not LIVESTOCK_OVERRIDE_ENABLED:
        return {"COW": DEFAULT_COW_CAP, "SHEEP": DEFAULT_SHEEP_CAP, "HERD": DEFAULT_HERD_CAP}
    return {"COW": ACTIVE_COW_CAP, "SHEEP": ACTIVE_SHEEP_CAP, "HERD": ACTIVE_HERD_CAP}


def get_active_animal_scaling() -> Dict[int, Tuple[int, int, int]]:
    """Authoritative runtime getter for animal scaling by workforce hands."""
    if not LIVESTOCK_OVERRIDE_ENABLED:
        return dict(DEFAULT_ANIMAL_SCALING)
    return dict(ANIMAL_SCALING)


def set_active_livestock_portfolio(
    cows: int,
    sheep: int,
    cow_cap: Optional[int] = None,
    sheep_cap: Optional[int] = None,
    herd_cap: Optional[int] = None,
    scaling: Optional[Dict[int, Tuple[int, int, int]]] = None,
) -> None:
    """Configure authoritative livestock portfolio targets and physical optimizer caps."""
    global LIVESTOCK_OVERRIDE_ENABLED, ACTIVE_TARGET_COWS, ACTIVE_TARGET_SHEEP
    global ACTIVE_COW_CAP, ACTIVE_SHEEP_CAP, ACTIVE_HERD_CAP, ANIMAL_SCALING
    global TARGET_COWS, TARGET_SHEEP

    LIVESTOCK_OVERRIDE_ENABLED = True
    ACTIVE_TARGET_COWS = int(cows)
    ACTIVE_TARGET_SHEEP = int(sheep)
    TARGET_COWS = int(cows)
    TARGET_SHEEP = int(sheep)

    # Physical caps for the optimizer: the arm cannot exceed these counts
    ACTIVE_COW_CAP = int(cows) if cow_cap is None else int(cow_cap)
    ACTIVE_SHEEP_CAP = int(sheep) if sheep_cap is None else int(sheep_cap)
    ACTIVE_HERD_CAP = (int(cows) + int(sheep)) if herd_cap is None else int(herd_cap)

    if scaling is not None:
        ANIMAL_SCALING = dict(scaling)
    else:
        # Generate proportional milestone scaling based on targets
        ANIMAL_SCALING = {
            4: (0, min(2, cows), min(2, sheep)),
            8: (0, min(cows, max(1, int(round(cows * 0.6)))), min(sheep, max(1, int(round(sheep * 0.6))))),
            10: (0, min(cows, max(1, int(round(cows * 0.85)))), min(sheep, max(1, int(round(sheep * 0.85))))),
            12: (0, cows, sheep),
        }

    # Synchronize loaded modules to prevent stale references
    try:
        import strategy.animal_planner as ap
        ap.COW_CAP = ACTIVE_COW_CAP
        ap.SHEEP_CAP = ACTIVE_SHEEP_CAP
        ap.HERD_CAP = ACTIVE_HERD_CAP
    except Exception:
        pass
    try:
        import strategy.pasture_planner as pp
        pp.COW_CAP = ACTIVE_COW_CAP
        pp.SHEEP_CAP = ACTIVE_SHEEP_CAP
        pp.HERD_CAP = ACTIVE_HERD_CAP
    except Exception:
        pass
    try:
        import strategy.land_serviceability_model as lsm
        lsm.TARGET_COWS = ACTIVE_TARGET_COWS
        lsm.TARGET_SHEEP = ACTIVE_TARGET_SHEEP
    except Exception:
        pass


def reset_livestock_portfolio() -> None:
    """Reset livestock portfolio to exact 588b3f1 baseline defaults."""
    global LIVESTOCK_OVERRIDE_ENABLED, ACTIVE_TARGET_COWS, ACTIVE_TARGET_SHEEP
    global ACTIVE_COW_CAP, ACTIVE_SHEEP_CAP, ACTIVE_HERD_CAP, ANIMAL_SCALING
    global TARGET_COWS, TARGET_SHEEP

    LIVESTOCK_OVERRIDE_ENABLED = False
    ACTIVE_TARGET_COWS = DEFAULT_TARGET_COWS
    ACTIVE_TARGET_SHEEP = DEFAULT_TARGET_SHEEP
    TARGET_COWS = DEFAULT_TARGET_COWS
    TARGET_SHEEP = DEFAULT_TARGET_SHEEP
    ACTIVE_COW_CAP = DEFAULT_COW_CAP
    ACTIVE_SHEEP_CAP = DEFAULT_SHEEP_CAP
    ACTIVE_HERD_CAP = DEFAULT_HERD_CAP
    ANIMAL_SCALING = dict(DEFAULT_ANIMAL_SCALING)

    try:
        import strategy.animal_planner as ap
        ap.COW_CAP = DEFAULT_COW_CAP
        ap.SHEEP_CAP = DEFAULT_SHEEP_CAP
        ap.HERD_CAP = DEFAULT_HERD_CAP
    except Exception:
        pass
    try:
        import strategy.pasture_planner as pp
        pp.COW_CAP = DEFAULT_COW_CAP
        pp.SHEEP_CAP = DEFAULT_SHEEP_CAP
        pp.HERD_CAP = DEFAULT_HERD_CAP
    except Exception:
        pass
    try:
        import strategy.land_serviceability_model as lsm
        lsm.TARGET_COWS = DEFAULT_TARGET_COWS
        lsm.TARGET_SHEEP = DEFAULT_TARGET_SHEEP
    except Exception:
        pass


def set_dynamic_sw_crops(enabled: bool) -> None:
    """Configure dynamic SW crop evaluation."""
    global DYNAMIC_SW_CROPS_ENABLED
    DYNAMIC_SW_CROPS_ENABLED = bool(enabled)


def set_strategic_sw_ownership(enabled: bool) -> None:
    """Configure strategic SW ownership policy."""
    global STRATEGIC_SW_OWNERSHIP_ENABLED
    STRATEGIC_SW_OWNERSHIP_ENABLED = bool(enabled)
    for mod_name in (
        "agent.strategy.expansion_planner", "strategy.expansion_planner", "expansion_planner",
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
        "agent.strategy.land_serviceability_model", "strategy.land_serviceability_model", "land_serviceability_model",
        "agent.execution.task_scheduler", "execution.task_scheduler", "task_scheduler",
    ):
        if mod_name in sys.modules:
            try:
                setattr(sys.modules[mod_name], "STRATEGIC_SW_OWNERSHIP_ENABLED", bool(enabled))
            except Exception:
                pass


SW_FORCE_K_TILES: Optional[int] = None

def set_sw_force_k(k: Optional[int]) -> None:
    """Configure forced k tile activation in SW (None for dynamic selection)."""
    global SW_FORCE_K_TILES
    SW_FORCE_K_TILES = k
    try:
        import strategy.land_serviceability_model as lsm
        lsm.SW_FORCE_K_TILES = k
    except Exception:
        pass


# Stage 8B Phase 1A: C4 — Late-Game Livestock Investment Cap
# Stage 8A empirical cutoff boundary: Day 12. Animals purchased Day 12+ fail to amortize
# capital cost, pasture build cost, feed procurement, and care opportunity costs.
C4_LIVESTOCK_CUTOFF_DAY = 12

# Selective Market-Aware Livestock Gate (Enabled in production with housing safety)
SELECTIVE_LIVESTOCK_GATE_ENABLED = True
SELECTIVE_LIVESTOCK_GATE_THRESHOLD = 500.0
SELECTIVE_LIVESTOCK_MAX_DAY = 14
SELECTIVE_LIVESTOCK_GATE_MAX_DAY = 14

# SW Land Serviceability and Partial Exploitation
# Isolated P1 experiment: the PURCHASE gate reserves observed livestock/housing
# workload instead of hypothetical desired-herd expansion. Defaults OFF, leaving
# existing production and all activation/feed serviceability callers unchanged.
SW_P1_PURCHASE_COMMITTED_HERD_ONLY = False

# Isolated P1.1 experiment: make only the task scheduler's SW home-worker
# allocation workload-responsive.  Default OFF preserves production Rule W1.
SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED = False


def set_sw_workload_responsive_scheduler(enabled: bool) -> None:
    """Toggle the isolated scheduler-only SW workload allocation experiment."""
    global SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED
    SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED = bool(enabled)
    for mod_name in (
        "agent.execution.task_scheduler", "execution.task_scheduler", "task_scheduler",
    ):
        if mod_name in sys.modules:
            try:
                setattr(
                    sys.modules[mod_name],
                    "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED",
                    bool(enabled),
                )
            except Exception:
                pass


def get_sw_workload_responsive_scheduler() -> bool:
    """Return whether the isolated workload-responsive SW scheduler is enabled."""
    return SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED


# Isolated P1.2 experiment: gate post-purchase SW crop activation on the
# serviceability model evaluated with the same surplus-capacity concept as the
# responsive scheduler. Default OFF preserves all existing production/P1/P1.1
# behavior exactly.
SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED = False


def set_sw_serviceability_aware_activation(enabled: bool) -> None:
    """Toggle the isolated P1.2 SW activation serviceability gate."""
    global SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED
    SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED = bool(enabled)
    for mod_name in (
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
    ):
        if mod_name in sys.modules:
            try:
                setattr(
                    sys.modules[mod_name],
                    "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED",
                    bool(enabled),
                )
            except Exception:
                pass


def get_sw_serviceability_aware_activation() -> bool:
    """Return whether post-purchase SW activation is serviceability-gated."""
    return SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED


# Isolated P1.3-A: keep *generic* planting away from SW when the SW-specific
# activation controller owns the SW agricultural footprint. Default OFF is
# required to reproduce the exact validated P1.2 runtime.
SW_GENERIC_PLANTING_GATE_ENABLED = False


def set_sw_generic_planting_gate(enabled: bool) -> None:
    """Toggle the isolated P1.3-A generic SW planting restriction."""
    global SW_GENERIC_PLANTING_GATE_ENABLED
    SW_GENERIC_PLANTING_GATE_ENABLED = bool(enabled)
    for mod_name in (
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
    ):
        if mod_name in sys.modules:
            try:
                setattr(
                    sys.modules[mod_name],
                    "SW_GENERIC_PLANTING_GATE_ENABLED",
                    bool(enabled),
                )
            except Exception:
                pass


def get_sw_generic_planting_gate() -> bool:
    """Return whether generic SW planting is restricted to the SW controller."""
    return SW_GENERIC_PLANTING_GATE_ENABLED

# None for dynamic model (optimal k* in {5, 10, 15}), or int in (5, 10, 15)
SW_FORCE_K_TILES = None


def set_sw_force_k_tiles(k) -> None:
    """Configure the forced SW soil tile count for A/B testing (None for dynamic model)."""
    global SW_FORCE_K_TILES
    SW_FORCE_K_TILES = k
    try:
        import strategy.land_serviceability_model as lsm
        lsm.SW_FORCE_K_TILES = k
    except Exception:
        pass


# Stage 8B Phase 2B: Workload-Aware Dynamic Zonal Allocation
DYNAMIC_ZONAL_ALLOCATION = False


def set_dynamic_zonal_allocation(enabled: bool) -> None:
    """Configure workload-aware dynamic zonal allocation (replaces Rule W1 squad partition)."""
    global DYNAMIC_ZONAL_ALLOCATION
    DYNAMIC_ZONAL_ALLOCATION = bool(enabled)
    for mod_name in (
        "agent.execution.task_scheduler", "execution.task_scheduler", "task_scheduler",
        "agent.strategy.land_serviceability_model", "strategy.land_serviceability_model", "land_serviceability_model",
    ):
        if mod_name in sys.modules:
            try:
                setattr(sys.modules[mod_name], "DYNAMIC_ZONAL_ALLOCATION", bool(enabled))
            except Exception:
                pass


def get_dynamic_zonal_allocation() -> bool:
    """Return whether workload-aware dynamic zonal allocation is enabled."""
    return DYNAMIC_ZONAL_ALLOCATION


# Persistent Worker Home Locality with Hysteresis
PERSISTENT_WORKER_LOCALITY_ENABLED = False
LOCALITY_ZONE_SWITCH_PENALTY = 15.0


def set_persistent_worker_locality(enabled: bool) -> None:
    """Configure persistent worker home locality with hysteresis."""
    global PERSISTENT_WORKER_LOCALITY_ENABLED
    PERSISTENT_WORKER_LOCALITY_ENABLED = bool(enabled)
    for mod_name in (
        "agent.execution.task_scheduler", "execution.task_scheduler", "task_scheduler",
    ):
        if mod_name in sys.modules:
            try:
                setattr(sys.modules[mod_name], "PERSISTENT_WORKER_LOCALITY_ENABLED", bool(enabled))
            except Exception:
                pass


def get_persistent_worker_locality() -> bool:
    """Return whether persistent worker locality is enabled."""
    return PERSISTENT_WORKER_LOCALITY_ENABLED


# SW Controlled Mixed Livestock Housing Cell (ArmC-Cell)
SW_CELL_HOUSING_ENABLED = False
SW_CELL_MAX_PASTURES = 1


def set_sw_cell_housing(enabled: bool) -> None:
    """Configure controlled SW livestock housing allocation."""
    global SW_CELL_HOUSING_ENABLED
    SW_CELL_HOUSING_ENABLED = bool(enabled)
    for mod_name in (
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
        "agent.strategy.pasture_planner", "strategy.pasture_planner", "pasture_planner",
        "agent.strategy.sw_cell_allocator", "strategy.sw_cell_allocator", "sw_cell_allocator",
    ):
        if mod_name in sys.modules:
            try:
                setattr(sys.modules[mod_name], "SW_CELL_HOUSING_ENABLED", bool(enabled))
            except Exception:
                pass


def get_sw_cell_housing() -> bool:
    """Return whether SW cell housing allocation is enabled."""
    return SW_CELL_HOUSING_ENABLED


# SW delayed unlock day (e.g. Day 14 for delayed SW arm)
SW_DELAYED_UNLOCK_DAY = None


def set_sw_delayed_unlock_day(day) -> None:
    """Configure delayed SW unlock day for experimental benchmarking."""
    global SW_DELAYED_UNLOCK_DAY
    SW_DELAYED_UNLOCK_DAY = int(day) if day is not None else None
    try:
        import strategy.expansion_planner as ep
        ep.SW_DELAYED_UNLOCK_DAY = SW_DELAYED_UNLOCK_DAY
    except Exception:
        pass
    try:
        import expansion_planner as ep
        ep.SW_DELAYED_UNLOCK_DAY = SW_DELAYED_UNLOCK_DAY
    except Exception:
        pass



def set_selective_livestock_gate(enabled: bool, threshold: float = 500.0, max_day: int = 14) -> None:
    """Configure the selective market-aware livestock investment gate."""
    global SELECTIVE_LIVESTOCK_GATE_ENABLED, SELECTIVE_LIVESTOCK_GATE_THRESHOLD, SELECTIVE_LIVESTOCK_GATE_MAX_DAY
    SELECTIVE_LIVESTOCK_GATE_ENABLED = bool(enabled)
    SELECTIVE_LIVESTOCK_GATE_THRESHOLD = float(threshold)
    SELECTIVE_LIVESTOCK_MAX_DAY = int(max_day)
    try:
        import strategy.animal_planner as ap
        ap.SELECTIVE_LIVESTOCK_GATE_ENABLED = bool(enabled)
        ap.SELECTIVE_LIVESTOCK_GATE_THRESHOLD = float(threshold)
        ap.SELECTIVE_LIVESTOCK_MAX_DAY = int(max_day)
    except Exception:
        pass
    try:
        import strategy.macro_planner as mp
        mp.SELECTIVE_LIVESTOCK_GATE_ENABLED = bool(enabled)
        mp.SELECTIVE_LIVESTOCK_GATE_THRESHOLD = float(threshold)
        mp.SELECTIVE_LIVESTOCK_MAX_DAY = int(max_day)
    except Exception:
        pass
    try:
        import strategy.pasture_planner as pp
        pp.SELECTIVE_LIVESTOCK_GATE_ENABLED = bool(enabled)
        pp.SELECTIVE_LIVESTOCK_GATE_THRESHOLD = float(threshold)
        pp.SELECTIVE_LIVESTOCK_MAX_DAY = int(max_day)
    except Exception:
        pass
    try:
        import market.order_builder as ob
        ob.SELECTIVE_LIVESTOCK_GATE_ENABLED = bool(enabled)
        ob.SELECTIVE_LIVESTOCK_GATE_THRESHOLD = float(threshold)
        ob.SELECTIVE_LIVESTOCK_MAX_DAY = int(max_day)
    except Exception:
        pass


def set_livestock_cutoff_day(day: int) -> None:
    """Set the livestock investment cutoff day for A/B testing."""
    global C4_LIVESTOCK_CUTOFF_DAY
    C4_LIVESTOCK_CUTOFF_DAY = int(day)
    try:
        import strategy.animal_planner as ap
        ap.C4_LIVESTOCK_CUTOFF_DAY = int(day)
    except Exception:
        pass
    try:
        import strategy.macro_planner as mp
        mp.C4_LIVESTOCK_CUTOFF_DAY = int(day)
    except Exception:
        pass
    try:
        import strategy.pasture_planner as pp
        pp.C4_LIVESTOCK_CUTOFF_DAY = int(day)
    except Exception:
        pass
    try:
        import market.order_builder as ob
        ob.C4_LIVESTOCK_CUTOFF_DAY = int(day)
    except Exception:
        pass


def get_livestock_cutoff_day() -> int:
    """Return the currently configured livestock cutoff day."""
    return C4_LIVESTOCK_CUTOFF_DAY


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

# ---------------------------------------------------------------- arbitration ----
# Authoritative arbitration mode:
# - "historical_candidates_central": Production default. Proven benchmark winner ($70,404.08 mean,
#   $59,957.60 B10 mean, zero P0 inversions, zero feed failures, zero critical wheat rejections).
# - "historical_stack": Historical fallback ($69,488.06 mean).
# - "central": CentralPlanner with default settings.
ARBITRATION_MODE = "historical_candidates_central"
USE_CENTRAL_PLANNER = (ARBITRATION_MODE in ("central", "historical_candidates_central", "expanded_central"))


# ====================================================================
# SW Isolated Experiment Settings (Arms A, B, C, D)
# ====================================================================
SW_OWNERSHIP_MODE: str = "production"       # "production", "early_liquidity", "pure_economic"
SW_TIMING_PRIOR_ENABLED: bool = False       # True for Arm C (soft D8/9 prior)
SW_ACTIVATION_MODE: str = "production"      # "production", "discrete", "progressive"
SW_SAFETY_RESERVE: float = 300.0            # Frozen at $300 across all arms


def set_sw_experiment_arm(arm: str) -> None:
    """Configure authoritative flags for SW experiment arms A, B, B-P, C-Cell, C, D."""
    global SW_OWNERSHIP_MODE, SW_TIMING_PRIOR_ENABLED, SW_ACTIVATION_MODE
    global STRATEGIC_SW_OWNERSHIP_ENABLED, DYNAMIC_ZONAL_ALLOCATION, DYNAMIC_SW_CROPS_ENABLED
    global PERSISTENT_WORKER_LOCALITY_ENABLED, SW_CELL_HOUSING_ENABLED
    global SW_P1_PURCHASE_COMMITTED_HERD_ONLY
    global SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED
    global SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED
    global SW_GENERIC_PLANTING_GATE_ENABLED
    arm_clean = str(arm).strip()
    if arm_clean == "ArmA":
        # Arm A — Fresh Production Control: Current strategy with SW expansion disabled/frozen
        set_quadrant_hard_block({3, 4})
        SW_OWNERSHIP_MODE = "production"
        SW_TIMING_PRIOR_ENABLED = False
        SW_ACTIVATION_MODE = "production"
        STRATEGIC_SW_OWNERSHIP_ENABLED = False
        DYNAMIC_ZONAL_ALLOCATION = False
        DYNAMIC_SW_CROPS_ENABLED = False
        PERSISTENT_WORKER_LOCALITY_ENABLED = False
        SW_CELL_HOUSING_ENABLED = False
        # Reset isolated P1/P1.1/P1.2 switches so ArmA is a true production
        # control even after another arm enabled them in the same process.
        SW_P1_PURCHASE_COMMITTED_HERD_ONLY = False
        SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED = False
        SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED = False
        SW_GENERIC_PLANTING_GATE_ENABLED = False
    elif arm_clean == "ArmC-Cell":
        # Arm C-Cell — Exactly Arm B-P + Controlled SW Mixed Livestock Housing Cell
        set_quadrant_hard_block({4})
        SW_OWNERSHIP_MODE = "early_liquidity"
        SW_TIMING_PRIOR_ENABLED = False
        SW_ACTIVATION_MODE = "discrete"
        STRATEGIC_SW_OWNERSHIP_ENABLED = True
        DYNAMIC_ZONAL_ALLOCATION = True
        DYNAMIC_SW_CROPS_ENABLED = True
        PERSISTENT_WORKER_LOCALITY_ENABLED = True
        SW_CELL_HOUSING_ENABLED = True
    elif arm_clean == "ArmB-P":
        # Arm B-P — Exactly Arm B + Persistent Worker Locality
        set_quadrant_hard_block({4})
        SW_OWNERSHIP_MODE = "early_liquidity"
        SW_TIMING_PRIOR_ENABLED = False
        SW_ACTIVATION_MODE = "discrete"
        STRATEGIC_SW_OWNERSHIP_ENABLED = True
        DYNAMIC_ZONAL_ALLOCATION = True
        DYNAMIC_SW_CROPS_ENABLED = True
        PERSISTENT_WORKER_LOCALITY_ENABLED = True
        SW_CELL_HOUSING_ENABLED = False
    elif arm_clean == "ArmB":
        # Arm B — Working SW + Discrete Activation (baseline dynamic allocation without persistent locality)
        set_quadrant_hard_block({4})
        SW_OWNERSHIP_MODE = "early_liquidity"
        SW_TIMING_PRIOR_ENABLED = False
        SW_ACTIVATION_MODE = "discrete"
        STRATEGIC_SW_OWNERSHIP_ENABLED = True
        DYNAMIC_ZONAL_ALLOCATION = True
        DYNAMIC_SW_CROPS_ENABLED = True
        PERSISTENT_WORKER_LOCALITY_ENABLED = False
        SW_CELL_HOUSING_ENABLED = False
    elif arm_clean == "ArmC":
        # Arm C — Primary Treatment: Working SW + Survival-Aware Progressive Activation (no Dusta prior)
        set_quadrant_hard_block({4})
        SW_OWNERSHIP_MODE = "early_liquidity"
        SW_TIMING_PRIOR_ENABLED = False
        SW_ACTIVATION_MODE = "progressive"
        STRATEGIC_SW_OWNERSHIP_ENABLED = True
        DYNAMIC_ZONAL_ALLOCATION = True
        DYNAMIC_SW_CROPS_ENABLED = True
        PERSISTENT_WORKER_LOCALITY_ENABLED = False
        SW_CELL_HOUSING_ENABLED = False
    elif arm_clean == "ArmD":
        # Arm D — Dusta Prior + Survival-Aware Progressive Activation (differs from C by Dusta prior only)
        set_quadrant_hard_block({4})
        SW_OWNERSHIP_MODE = "early_liquidity"
        SW_TIMING_PRIOR_ENABLED = True
        SW_ACTIVATION_MODE = "progressive"
        STRATEGIC_SW_OWNERSHIP_ENABLED = True
        DYNAMIC_ZONAL_ALLOCATION = True
        DYNAMIC_SW_CROPS_ENABLED = True
        PERSISTENT_WORKER_LOCALITY_ENABLED = False
        SW_CELL_HOUSING_ENABLED = False
    else:
        raise ValueError(f"Unknown SW experiment arm: {arm}")

    # Synchronize loaded modules
    for mod_name in (
        "agent.strategy.expansion_planner", "strategy.expansion_planner", "expansion_planner",
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
        "agent.strategy.pasture_planner", "strategy.pasture_planner", "pasture_planner",
        "agent.strategy.sw_cell_allocator", "strategy.sw_cell_allocator", "sw_cell_allocator",
        "agent.strategy.land_serviceability_model", "strategy.land_serviceability_model", "land_serviceability_model",
        "agent.execution.task_scheduler", "execution.task_scheduler", "task_scheduler",
    ):
        if mod_name in sys.modules:
            try:
                mod = sys.modules[mod_name]
                for attr, val in (
                    ("SW_OWNERSHIP_MODE", SW_OWNERSHIP_MODE),
                    ("SW_TIMING_PRIOR_ENABLED", SW_TIMING_PRIOR_ENABLED),
                    ("SW_ACTIVATION_MODE", SW_ACTIVATION_MODE),
                    ("SW_SAFETY_RESERVE", SW_SAFETY_RESERVE),
                    ("STRATEGIC_SW_OWNERSHIP_ENABLED", STRATEGIC_SW_OWNERSHIP_ENABLED),
                    ("DYNAMIC_ZONAL_ALLOCATION", DYNAMIC_ZONAL_ALLOCATION),
                    ("DYNAMIC_SW_CROPS_ENABLED", DYNAMIC_SW_CROPS_ENABLED),
                    ("PERSISTENT_WORKER_LOCALITY_ENABLED", PERSISTENT_WORKER_LOCALITY_ENABLED),
                    ("SW_CELL_HOUSING_ENABLED", SW_CELL_HOUSING_ENABLED),
                    ("SW_P1_PURCHASE_COMMITTED_HERD_ONLY", SW_P1_PURCHASE_COMMITTED_HERD_ONLY),
                    ("SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED", SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED),
                    ("SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED", SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED),
                    ("SW_GENERIC_PLANTING_GATE_ENABLED", SW_GENERIC_PLANTING_GATE_ENABLED),
                ):
                    setattr(mod, attr, val)
            except Exception:
                pass


LIVESTOCK_EXPERIMENT_ARM: str = "ArmC"      # "ArmA" (production control), "ArmB" (target+shop econ), "ArmC" (dynamic allocator)


def set_livestock_experiment_arm(arm: str) -> None:
    """Configure authoritative flags for Livestock experiment arms A, B, C."""
    global LIVESTOCK_EXPERIMENT_ARM
    arm_clean = str(arm).strip()
    if "ArmA" in arm_clean:
        LIVESTOCK_EXPERIMENT_ARM = "ArmA"
    elif "ArmB" in arm_clean:
        LIVESTOCK_EXPERIMENT_ARM = "ArmB"
    elif "ArmC" in arm_clean:
        LIVESTOCK_EXPERIMENT_ARM = "ArmC"
    else:
        raise ValueError(f"Unknown livestock experiment arm: {arm}")

    for mod_name in (
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
        "agent.strategy.animal_planner", "strategy.animal_planner", "animal_planner",
    ):
        if mod_name in sys.modules:
            try:
                mod = sys.modules[mod_name]
                setattr(mod, "LIVESTOCK_EXPERIMENT_ARM", LIVESTOCK_EXPERIMENT_ARM)
            except Exception:
                pass


# Livestock Opponent Commitment Valuation Mode
# L0: Unconstrained counterfactual valuation (O0 baseline, ignores opponent animal commitments)
# L1: Unguarded commitment-aware livestock valuation (derives future supply scenarios from visible opponent animals)
# L2a: Guarded commitment awareness (conservative: relative_gap <= 0.05)
# L2b: Guarded commitment awareness (medium: relative_gap <= 0.15)
# L2c: Guarded commitment awareness (permissive: relative_gap <= 0.30)
# L2: Guarded commitment awareness with explicit LIVESTOCK_GUARD_THRESHOLD
LIVESTOCK_VALUATION_MODE: str = "L0"
LIVESTOCK_GUARD_THRESHOLD: float = 0.15


def set_livestock_valuation_mode(mode: str, guard_threshold: Optional[float] = None) -> None:
    """Configure livestock valuation mode: 'L0', 'L1', 'L2a', 'L2b', 'L2c', or 'L2'."""
    global LIVESTOCK_VALUATION_MODE, LIVESTOCK_GUARD_THRESHOLD
    mode_clean = str(mode).strip()
    mode_upper = mode_clean.upper()
    valid_modes = ("L0", "L1", "L2", "L2A", "L2B", "L2C")
    if mode_upper not in valid_modes:
        raise ValueError(f"Unknown livestock valuation mode: {mode}. Expected one of {valid_modes}")

    LIVESTOCK_VALUATION_MODE = mode_upper
    if mode_upper == "L2A":
        LIVESTOCK_GUARD_THRESHOLD = 0.05
    elif mode_upper == "L2B":
        LIVESTOCK_GUARD_THRESHOLD = 0.15
    elif mode_upper == "L2C":
        LIVESTOCK_GUARD_THRESHOLD = 0.30
    elif guard_threshold is not None:
        LIVESTOCK_GUARD_THRESHOLD = float(guard_threshold)

    for mod_name in (
        "agent.config", "config", "agent.main", "main",
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
        "agent.strategy.herd_planner", "strategy.herd_planner", "herd_planner",
        "agent.strategy.marginal_livestock_valuator", "strategy.marginal_livestock_valuator", "marginal_livestock_valuator",
    ):
        if mod_name in sys.modules:
            try:
                setattr(sys.modules[mod_name], "LIVESTOCK_VALUATION_MODE", LIVESTOCK_VALUATION_MODE)
                setattr(sys.modules[mod_name], "LIVESTOCK_GUARD_THRESHOLD", LIVESTOCK_GUARD_THRESHOLD)
            except Exception:
                pass


def get_livestock_valuation_mode() -> str:
    return LIVESTOCK_VALUATION_MODE


def get_livestock_guard_threshold() -> float:
    return LIVESTOCK_GUARD_THRESHOLD



def get_sw_experiment_settings() -> Dict[str, Any]:
    """Return immutable snapshot of current SW experiment settings."""
    return {
        "ownership_mode": SW_OWNERSHIP_MODE,
        "timing_prior_enabled": SW_TIMING_PRIOR_ENABLED,
        "activation_mode": SW_ACTIVATION_MODE,
        "safety_reserve": SW_SAFETY_RESERVE,
        "strategic_sw_ownership": STRATEGIC_SW_OWNERSHIP_ENABLED,
        "dynamic_zonal_allocation": DYNAMIC_ZONAL_ALLOCATION,
        "persistent_worker_locality": PERSISTENT_WORKER_LOCALITY_ENABLED,
        "sw_cell_housing_enabled": SW_CELL_HOUSING_ENABLED,
    }


# ====================================================================
# Opponent Intelligence Experiment Modes (O0, O0_SHADOW, O1, O1_SHADOW, O1R)
# ====================================================================
# O0 = opponent advice completely disabled (empty OpponentAdvice) - SAFE COMPETITION DEFAULT
# O0_SHADOW = exact O0 live decisions + repaired opponent model runs shadow telemetry only
# O1 = exact current opponent behavior (untouched baseline)
# O1_SHADOW = O1 still controls strategy + repaired forecasts run telemetry-only
# O1R = repaired intelligence affects strategy; disabled until calibration passes
OPPONENT_INTELLIGENCE_MODE: str = "O0_SHADOW"
SHADOW_OPPONENT_FORECAST_ENABLED: bool = True


def set_opponent_intelligence_mode(mode: str) -> None:
    """Configure opponent intelligence mode: O0, O0_SHADOW, O1, O1_SHADOW, O1R, A0, A1, A2, A3, A4."""
    global OPPONENT_INTELLIGENCE_MODE, SHADOW_OPPONENT_FORECAST_ENABLED
    mode_clean = str(mode).strip()
    valid_modes = ("O0", "O0_SHADOW", "O1", "O1_SHADOW", "O1R", "A0", "A1", "A2", "A3", "A4")
    if mode_clean not in valid_modes:
        raise ValueError(f"Unknown opponent intelligence mode: {mode}. Expected one of {valid_modes}")
    OPPONENT_INTELLIGENCE_MODE = mode_clean
    if mode_clean in ("O0_SHADOW", "O1_SHADOW", "A3", "A4"):
        SHADOW_OPPONENT_FORECAST_ENABLED = True
    elif mode_clean in ("O0", "O1", "A0", "A1", "A2"):
        SHADOW_OPPONENT_FORECAST_ENABLED = False

    for mod_name in (
        "agent.main", "main", "agent.config", "config",
        "agent.strategy.opponent_advisor", "strategy.opponent_advisor", "opponent_advisor",
    ):
        if mod_name in sys.modules:
            try:
                mod = sys.modules[mod_name]
                setattr(mod, "OPPONENT_INTELLIGENCE_MODE", OPPONENT_INTELLIGENCE_MODE)
                setattr(mod, "SHADOW_OPPONENT_FORECAST_ENABLED", SHADOW_OPPONENT_FORECAST_ENABLED)
            except Exception:
                pass


def get_opponent_intelligence_mode() -> str:
    return OPPONENT_INTELLIGENCE_MODE

