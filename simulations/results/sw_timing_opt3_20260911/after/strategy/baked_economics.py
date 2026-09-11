"""Baked asset economics artifact.

Authoritative source of season-long yield, cost, and lifecycle metrics
derived from simulations/profitability_calculator. Consumed by MacroPlanner
and validation test suites to eliminate mirror-drift footguns.
"""
from config import TARGET_COWS, TARGET_GEESE, TARGET_SHEEP

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
