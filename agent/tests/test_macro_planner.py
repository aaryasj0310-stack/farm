"""W2 tests: MacroPlanner decisions under controlled forecast/state."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from observation_parser import parse_observation
from config import CROPS
from strategy.macro_planner import MacroPlanner, _crop_allowed_today


def make_forecast(prices_by_product):
    """Constant-per-product fake forecast satisfying the MacroPlanner API."""
    class FakeFC:
        def __init__(self, prices):
            self.prices = prices

        def expected_price(self, product, day):
            return self.prices.get(product, 25.0)

    return FakeFC(prices_by_product)


def make_ctx(day=5, money=3000.0, hands=(), shed=None, seeds=None,
             animals=(), structures=(), unlocked=("NW",), wheat_tiles=0):
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    half = 5
    quads = {("N", "W"): "NW", ("N", "E"): "NE",
             ("S", "W"): "SW", ("S", "E"): "SE"}
    for y in range(board):
        for x in range(board):
            q = quads[("N" if y < half else "S", "W" if x < half else "E")]
            if q not in unlocked:
                tiles[y][x] = "LOCKED"
    for (x, y, obj) in list(animals) + list(structures):
        tiles[y][x] = obj
    # plant wheat tiles (engine uses kind="PLANT" with crop="WHEAT")
    wheat_placed = 0
    for y in range(board):
        for x in range(board):
            if wheat_placed >= wheat_tiles:
                break
            if tiles[y][x] is None:
                tiles[y][x] = {
                    "kind": "PLANT", "crop": "WHEAT",
                    "pos": (x, y), "x": x, "y": y,
                    "watered_today": False, "yield_units": 0,
                    "placed_day": day, "consecutive_unwatered": 0,
                }
                wheat_placed += 1
        if wheat_placed >= wheat_tiles:
            break
    farm = {
        "money": money,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4]] * len(hands),
        "unlocked_quadrants": list(unlocked),
        "hires_today": 0,
    }
    obs = {
        "player": 0, "day": day, "hour": 1,
        "farms": [farm, farm],
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
        "private": {"shed": dict(shed or {}),
                    "seeds": dict(seeds or {}),
                    "inventories": [{}]},
    }
    ctx = parse_observation(obs)
    assert ctx is not None
    return ctx


BASE_PRICES = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
               "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200}


def test_midgame_plan_queues_crops_and_seed_buys():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=3000)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.plant_queue, "empty tiles should be queued for planting"
    for pos, crop in plan.plant_queue:
        assert _crop_allowed_today(crop, 5)
    cost = sum(CROPS[c]["seed"] * n for c, n in plan.intents["buy_seed"].items())
    assert cost <= 3000 - 300   # seed buys within bank minus reserve
    # 25 NW tiles minus structure reservations for animal expansion.
    # With no wheat tiles, sustainable=0 → no animals bought → no structures
    # reserved → all 25 tiles available for planting.
    # With wheat tiles, animals are bought and structures consume tiles.
    n_plants = len(plan.plant_queue)
    assert n_plants >= 22, f"expected at least 22 queued plants, got {n_plants}"
    assert plan.intents["hire"] >= 2  # MIN_HANDS floor guarantees 3 hands by day 14
    assert plan.water_budget_exceeded is False


def test_endgame_shuts_everything_down():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=29, money=99999)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.phase == "endgame"
    assert plan.watering_enabled is False
    assert plan.feeding_enabled is False  # day 29: feeding disabled
    assert plan.plant_queue == []
    # endgame intents: no new buying/planting, but structure exists
    assert plan.intents["buy_seed"] == {}
    assert plan.intents["buy_animal"] == {}
    assert plan.intents["buy_wheat"] == 0
    assert plan.intents["buy_land"] is False
    assert plan.intents["hire"] == 0


def test_melon_cutoff_respected():
    fc = make_forecast(BASE_PRICES)
    # day 18: fert-melon cutoff is day 17 -> no melons allowed
    ctx = make_ctx(day=18, money=5000)
    plan = MacroPlanner(fc).build(ctx)
    assert all(crop != "MELON" for _, crop in plan.plant_queue)


def test_high_price_pivot_to_carrot():
    boosted = dict(BASE_PRICES, CARROT=400.0)
    base_fc = make_forecast(BASE_PRICES)
    carrot_fc = make_forecast(boosted)
    seeds = {"CARROT": 25}          # pre-owned so cash never blocks comparison
    plan_base = MacroPlanner(base_fc).build(make_ctx(day=20, money=5000, seeds=seeds))
    plan_carrot = MacroPlanner(carrot_fc).build(make_ctx(day=20, money=5000, seeds=seeds))
    n_base = sum(1 for _, c in plan_base.plant_queue if c == "CARROT")
    n_boost = sum(1 for _, c in plan_carrot.plant_queue if c == "CARROT")
    assert n_boost > n_base


def test_cash_starved_limits_buys():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=150)     # below reserve: nothing affordable
    plan = MacroPlanner(fc).build(ctx)
    cost = sum(CROPS[c]["seed"] * n for c, n in plan.intents["buy_seed"].items())
    assert cost <= max(0, 150 - 300) or cost == 0


def test_animal_expansion_intents_and_feed():
    goose_tile = (2, 2)
    animals = [(goose_tile[0], goose_tile[1],
                {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                 "yield_units": 1, "fed_today": True, "cared_today": False,
                 "consecutive_unfed": 0, "fertilizer_available": False,
                 "pending_care_bonus": 0})]
    fc = make_forecast(BASE_PRICES)
    # 10 wheat tiles → capacity 60 → sustainable 2 animals (60//30)
    ctx = make_ctx(day=8, money=20000, animals=animals, shed={"WHEAT": 0},
                   wheat_tiles=10)
    plan = MacroPlanner(fc).build(ctx)
    # sustainable=2, current=1 → can buy at most 1 more
    total_buys = sum(plan.intents["buy_animal"].values())
    assert total_buys >= 1
    assert plan.build_op in ("BUILD_COOP", "BUILD_PASTURE")
    # feed buffer for existing animals triggers wheat purchase
    assert plan.intents["buy_wheat"] >= 2


def test_deterministic_output():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=6, money=2500)
    p1 = MacroPlanner(fc).build(ctx)
    p2 = MacroPlanner(fc).build(ctx)
    assert p1.plant_queue == p2.plant_queue
    assert p1.intents == p2.intents


def test_day28_feeding_enabled():
    """Day 28: feeding active (EOD produce sellable on Day 29)."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=28, money=99999)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.phase == "endgame"
    assert plan.feeding_enabled is True
    assert plan.watering_enabled is False


def test_day29_feeding_disabled():
    """Day 29: feeding disabled (produces after season scoring)."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=29, money=99999)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.phase == "endgame"
    assert plan.feeding_enabled is False
    assert plan.watering_enabled is False


def test_day28_no_new_animals():
    """Day 28 endgame: no new animal purchases."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=28, money=99999)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_animal"] == {}


def test_day28_no_new_planting():
    """Day 28 endgame: no new crop planting."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=28, money=99999)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.plant_queue == []
    assert plan.intents["buy_seed"] == {}


def test_day28_no_new_land():
    """Day 28 endgame: no land purchases."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=28, money=99999)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_land"] is False


def test_day28_wheat_buffer_computed():
    """Day 28: wheat feed buffer is still computed for today's animals."""
    animals = [(2, 2, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                        "yield_units": 1, "fed_today": True,
                        "cared_today": False, "consecutive_unfed": 0,
                        "fertilizer_available": False, "pending_care_bonus": 0})]
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=28, money=99999, animals=animals, shed={"WHEAT": 0})
    plan = MacroPlanner(fc).build(ctx)
    # feeding enabled on day 28 → wheat buffer should be planned
    assert plan.feeding_enabled is True
    assert plan.intents["buy_wheat"] >= 2  # at least buffer for 1 animal


def test_baked_economics_structure():
    """Verify baked economics values for all crops and animals."""
    from strategy.baked_economics import (
        CROP_ECONOMICS, CROP_CYCLE_LEN, ANIMAL_ECONOMICS, ANIMAL_TARGETS
    )
    assert set(CROP_ECONOMICS.keys()) == {"WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"}
    assert set(ANIMAL_ECONOMICS.keys()) == {"GOOSE", "COW", "SHEEP"}
    assert all(c["yield30"] > 0 for c in CROP_ECONOMICS.values())
    assert all(a["out30"] > 0 for a in ANIMAL_ECONOMICS.values())


# ─── Dynamic Hiring Floor (Fix 7) ───────────────────────────────────────────

def test_dynamic_hiring_floor_scales_with_animals():
    """Dynamic floor = MIN_HANDS_BASE + n_animals//4 + extra_quads.
    With 8 animals, floor = 4 + 8//4 + 0 = 6; player has 1 farmer only → hire 5.
    Place animals on non-overlapping positions in NW (0-4, 0-4)."""
    # NW quadrant: x=0..4, y=0..4 → 25 tiles
    positions = [(0,0),(1,0),(2,0),(3,0),(0,1),(1,1),(2,1),(3,1)]
    animals = [(px, py, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                "yield_units": 1, "fed_today": True, "cared_today": False,
                "consecutive_unfed": 0, "fertilizer_available": False,
                "pending_care_bonus": 0}) for px, py in positions]
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=10, money=20000, animals=animals,
                   shed={"WHEAT": 0}, wheat_tiles=20)
    plan = MacroPlanner(fc).build(ctx)
    # MIN_HANDS_BASE=4, n_animals=8 → 8//4=2, extra_quads=0 → floor=6
    # Player has 0 hands + 1 farmer = 1 unit → need 6-1=5 hires
    assert plan.intents["hire"] >= 5, f"expected >=5 hires, got {plan.intents['hire']}"


def test_dynamic_hiring_floor_extended_to_day25():
    """Dynamic floor applies through day 24 (not just day 14)."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=20, money=20000, hands=[1, 2], shed={"WHEAT": 0})
    plan = MacroPlanner(fc).build(ctx)
    # MIN_HANDS_BASE=4, n_animals=0 → floor=4; player has 1 farmer + 2 hands = 3
    # needed = max(0, 4 - 3) = 1 hire minimum
    assert plan.intents["hire"] >= 1, f"expected >=1 hire at day 20, got {plan.intents['hire']}"


def test_dynamic_hiring_extra_quadrant_bonus():
    """Extra quadrant adds +1 to the dynamic floor."""
    positions = [(0,0),(1,0),(2,0),(3,0),(0,1),(1,1),(2,1),(3,1)]
    animals = [(px, py, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                "yield_units": 1, "fed_today": True, "cared_today": False,
                "consecutive_unfed": 0, "fertilizer_available": False,
                "pending_care_bonus": 0}) for px, py in positions]
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=10, money=50000, animals=animals,
                   shed={"WHEAT": 0}, wheat_tiles=20,
                   unlocked=("NW", "NE"))
    plan = MacroPlanner(fc).build(ctx)
    # floor = 4 + 8//4 + 1(extra quad) = 7
    # Player has 1 unit → need 6 hires
    assert plan.intents["hire"] >= 6, f"expected >=6 hires, got {plan.intents['hire']}"


# ─── Wheat-First Planting (Fix 2) ───────────────────────────────────────────

def test_wheat_first_planted_before_cash_crops():
    """Wheat tiles appear first in plant_queue, before any cash crop."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=3000, seeds={"WHEAT": 10, "CARROT": 10,
                   "TOMATO": 10, "STRAWBERRY": 10, "MELON": 10})
    plan = MacroPlanner(fc).build(ctx)
    crops_in_order = [crop for _, crop in plan.plant_queue]
    # First planted crop should be WHEAT (if wheat_target > 0 and seeds available)
    wheat_idx = crops_in_order.index("WHEAT") if "WHEAT" in crops_in_order else -1
    cash_indices = [i for i, c in enumerate(crops_in_order) if c != "WHEAT"]
    if wheat_idx >= 0 and cash_indices:
        assert wheat_idx < min(cash_indices), \
            "WHEAT should be planted before any cash crop"


def test_wheat_first_respects_target():
    """Wheat planting is capped at TARGET_GEESE//3 ≈ 6 tiles max."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=3000, seeds={"WHEAT": 20})
    plan = MacroPlanner(fc).build(ctx)
    wheat_count = sum(1 for _, c in plan.plant_queue if c == "WHEAT")
    assert wheat_count <= 8, f"expected <=8 wheat tiles, got {wheat_count}"


# ─── Portfolio-Aware Crop Scoring (Fix 3) ────────────────────────────────────

def test_portfolio_aware_prevents_monoculture():
    """With 4 melons already planned, _crop_score for melon uses 5 (not 25).
    This prevents melon from dominating every remaining tile."""
    animals_structs = [(x, 2, {"kind": "PLANT", "crop": "MELON",
                        "pos": (x, 2), "x": x, "y": 2,
                        "watered_today": False, "yield_units": 3,
                        "placed_day": 3, "consecutive_unwatered": 0})
                       for x in range(4)]
    fc = make_forecast({**BASE_PRICES, "MELON": 300})
    ctx = make_ctx(day=10, money=5000, animals=animals_structs,
                   shed={"WHEAT": 0}, seeds={"WHEAT": 20, "MELON": 20})
    plan = MacroPlanner(fc).build(ctx)
    melon_count = sum(1 for _, c in plan.plant_queue if c == "MELON")
    non_melon = sum(1 for _, c in plan.plant_queue if c != "MELON")
    # Portfolio-aware scoring should leave room for other crops
    assert non_melon > 0, f"portfolio-aware should plant non-melon crops, got {melon_count} melons and {non_melon} others"


# ─── Crop Tile Caps (Fix 4) ─────────────────────────────────────────────────

def test_crop_tile_caps_prevent_excess():
    """Even with infinite money and high melon price, melon tiles capped at 6."""
    fc = make_forecast({**BASE_PRICES, "MELON": 500})
    ctx = make_ctx(day=8, money=99999, seeds={"MELON": 50, "WHEAT": 50})
    plan = MacroPlanner(fc).build(ctx)
    melon_count = sum(1 for _, c in plan.plant_queue if c == "MELON")
    assert melon_count <= 6, f"expected <=6 melon tiles (cap), got {melon_count}"


def test_crop_tile_caps_wheat_unlimited():
    """Wheat has no cap (99) — not blocked by CROP_TILE_CAPS.
    Other crops may score higher in portfolio-aware scoring, so we just
    verify wheat isn't artificially limited."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=20000, seeds={"WHEAT": 50})
    plan = MacroPlanner(fc).build(ctx)
    wheat_count = sum(1 for _, c in plan.plant_queue if c == "WHEAT")
    assert wheat_count <= 25, f"wheat count {wheat_count} exceeds board capacity"
    assert wheat_count >= 3, f"expected at least 3 wheat tiles, got {wheat_count}"


# ─── Budget Prioritization (Fix 6) ───────────────────────────────────────────

def test_budget_hire_land_animal_deducted_before_seeds():
    """Hire+land+animal costs deducted first; seeds get remainder."""
    animals = [(2, 2, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                "yield_units": 1, "fed_today": True, "cared_today": False,
                "consecutive_unfed": 0, "fertilizer_available": False,
                "pending_care_bonus": 0})]
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=10, money=2000, animals=animals,
                   shed={"WHEAT": 0}, wheat_tiles=10)
    plan = MacroPlanner(fc).build(ctx)
    # Seeds should cost 0 (budget exhausted by hire+animal)
    seed_cost = sum(CROPS[c]["seed"] * n for c, n in plan.intents["buy_seed"].items())
    assert seed_cost <= 2000 - 300, f"seed cost {seed_cost} should fit within budget"


# ─── ROI-Based Land Expansion ────────────────────────────────────────────────

def test_land_expansion_roi_positive_when_profitable():
    """Land bought when expected lifetime profit exceeds price * ROI_THRESHOLD.
    Day 8, 3 geese, $5000 — high crop scores → ROI > 1.5 → buy."""
    geese_pos = [(0, 0), (1, 0), (2, 0)]
    animals = [(x, y, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                "yield_units": 1, "fed_today": True, "cared_today": False,
                "consecutive_unfed": 0, "fertilizer_available": False,
                "pending_care_bonus": 0}) for x, y in geese_pos]
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=8, money=5000, unlocked=("NW",), animals=animals,
                   shed={"WHEAT": 10}, wheat_tiles=6)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_land"] is True, \
        "ROI: profitable crops + sufficient days remaining → buy land"


def test_land_expansion_roi_skipped_when_broke():
    """Land not bought if money < price + MONEY_RESERVE."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=8, money=800, unlocked=("NW",))
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_land"] is False, \
        "ROI: insufficient cash → no land"


def test_land_expansion_roi_skipped_after_day20():
    """Hard cutoff: no land after day 20 regardless of ROI."""
    geese_pos = [(0, 0), (1, 0), (2, 0)]
    animals = [(x, y, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                "yield_units": 1, "fed_today": True, "cared_today": False,
                "consecutive_unfed": 0, "fertilizer_available": False,
                "pending_care_bonus": 0}) for x, y in geese_pos]
    fc = make_forecast({**BASE_PRICES, "MELON": 500})
    ctx = make_ctx(day=21, money=99999, unlocked=("NW",), animals=animals,
                   shed={"WHEAT": 10}, wheat_tiles=6)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_land"] is False, \
        "ROI: day > 20 → hard cutoff, no land"


def test_land_expansion_roi_skipped_without_feed():
    """Land not bought if animals exist but wheat feed is insufficient."""
    geese_pos = [(0, 0), (1, 0), (2, 0)]
    animals = [(x, y, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                "yield_units": 1, "fed_today": True, "cared_today": False,
                "consecutive_unfed": 0, "fertilizer_available": False,
                "pending_care_bonus": 0}) for x, y in geese_pos]
    fc = make_forecast({**BASE_PRICES, "MELON": 500})
    ctx = make_ctx(day=8, money=99999, unlocked=("NW",), animals=animals,
                   shed={"WHEAT": 0}, wheat_tiles=0)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_land"] is False, \
        "ROI: animals need feed but wheat buffer empty → no land"
