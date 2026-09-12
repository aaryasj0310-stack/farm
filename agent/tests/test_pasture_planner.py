"""Unit tests for PasturePlanner and dynamic pasture capacity.

Verifies:
- Test A: Capacity above 9 (existing pastures = 9, viable NW/NE candidates -> dynamic capacity >= 10).
- Test B: Old SW list is not a hard cap (exhaust SW, NW/NE candidates still qualify).
- Test C: Distance ranking (distance 1 ranks before distance 5).
- Test D: Crop opportunity rejection (high crop opportunity rejects marginal pasture).
- Test E: Positive livestock conversion (livestock profit > crop opportunity + costs -> accepted).
- Test F: Feed cap remains binding (feed sustainable cap clamps final target).
- Test G: HERD_CAP remains binding (effective cap <= 20).
- Test H: Locked quadrants ignored (SE and locked tiles never candidates).
- Test I: Shed-access tiles protected (SHED_ACCESS_TILES and PORT_SW strictly excluded).
- Test J: Live crops not destroyed (only empty tiles eligible).
- Test K: Only queued build tiles removed from crop queue (unbuilt SW tiles remain available for planting).
"""
import pytest
from observation_parser import parse_observation
from config import SHED_ACCESS_TILES, PORT_SW
from strategy.animal_planner import (
    HERD_CAP,
    COW_CAP,
    SHEEP_CAP,
    estimate_species_remaining_profit,
    get_animal_targets,
)
from strategy.pasture_planner import (
    distance_to_shed,
    get_marginal_animal_profit_sequence,
    estimate_crop_opportunity_value,
    evaluate_pasture_candidates,
    BUILD_ACTION_OPPORTUNITY_COST,
)
from strategy.macro_planner import MacroPlanner


def make_test_farm(day=3, money=5000.0, unlocked=("NW", "SW", "NE"), structures=(), animals=(), crops=()):
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    half = 5
    quads = {("N", "W"): "NW", ("N", "E"): "NE", ("S", "W"): "SW", ("S", "E"): "SE"}

    for y in range(board):
        for x in range(board):
            q = quads[("N" if y < half else "S", "W" if x < half else "E")]
            if q not in unlocked:
                tiles[y][x] = "LOCKED"

    for (x, y, obj) in list(structures) + list(animals):
        tiles[y][x] = obj

    for (x, y, crop_name) in crops:
        tiles[y][x] = {
            "kind": "PLANT",
            "crop": crop_name,
            "pos": (x, y),
            "x": x,
            "y": y,
            "watered_today": False,
            "yield_units": 0,
            "placed_day": day,
            "consecutive_unwatered": 0,
        }

    farm = {
        "money": money,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4]],
        "unlocked_quadrants": list(unlocked),
        "hires_today": 0,
    }

    obs = {
        "player": 0,
        "day": day,
        "hour": 0,
        "farms": [farm, farm],
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
        "private": {
            "shed": {"WHEAT": 50, "MILK": 0, "WOOL": 0, "FERTILIZER": 0},
            "seeds": {},
            "inventories": [{}],
        },
    }
    ctx = parse_observation(obs)
    assert ctx is not None
    return ctx["farm"]


class FakeForecast:
    def __init__(self, prices=None):
        self.prices = prices or {}

    def expected_price(self, product, day):
        return self.prices.get(product, 25.0)


def test_distance_to_shed():
    # Immediate neighbor of shed access tile
    assert distance_to_shed((4, 3)) == 1
    # Check that distance is always >= 1 for non-shed tiles
    assert distance_to_shed((0, 0)) > 1


def test_case_a_capacity_above_nine():
    """Existing pastures = 9, viable NW/NE candidates -> dynamic capacity >= 10."""
    sw_pastures = [
        (0, 5, {"kind": "PASTURE", "x": 0, "y": 5}),
        (0, 6, {"kind": "PASTURE", "x": 0, "y": 6}),
        (0, 7, {"kind": "PASTURE", "x": 0, "y": 7}),
        (1, 5, {"kind": "PASTURE", "x": 1, "y": 5}),
        (1, 6, {"kind": "PASTURE", "x": 1, "y": 6}),
        (1, 7, {"kind": "PASTURE", "x": 1, "y": 7}),
        (2, 5, {"kind": "PASTURE", "x": 2, "y": 5}),
        (2, 6, {"kind": "PASTURE", "x": 2, "y": 6}),
        (2, 7, {"kind": "PASTURE", "x": 2, "y": 7}),
    ]
def _eval_helper(farm_state, fc, day=3):
    empty_tiles = [
        (t.x, t.y) for t in farm_state.iter_tiles()
        if getattr(t, "kind", None) == "EMPTY"
    ]
    counts = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    for t in farm_state.iter_tiles():
        if getattr(t, "animal", None):
            counts[t.animal] = counts.get(t.animal, 0) + 1

    from strategy.macro_planner import _crop_score, _crop_allowed_today
    crop_opp_val, best_crop = estimate_crop_opportunity_value(
        day=day,
        forecast=fc,
        crop_score_func=_crop_score,
        crop_allowed_func=_crop_allowed_today,
    )
    return evaluate_pasture_candidates(
        farm=farm_state,
        day=day,
        empty_tiles=empty_tiles,
        current_animals=counts,
        crop_opportunity_val=crop_opp_val,
        crop_name=best_crop,
    )


def test_case_a_capacity_above_nine():
    """Existing pastures = 9, viable NW/NE candidates -> dynamic capacity >= 10."""
    sw_pastures = [
        (0, 5, {"kind": "PASTURE", "x": 0, "y": 5}),
        (0, 6, {"kind": "PASTURE", "x": 0, "y": 6}),
        (0, 7, {"kind": "PASTURE", "x": 0, "y": 7}),
        (1, 5, {"kind": "PASTURE", "x": 1, "y": 5}),
        (1, 6, {"kind": "PASTURE", "x": 1, "y": 6}),
        (1, 7, {"kind": "PASTURE", "x": 1, "y": 7}),
        (2, 5, {"kind": "PASTURE", "x": 2, "y": 5}),
        (2, 6, {"kind": "PASTURE", "x": 2, "y": 6}),
        (2, 7, {"kind": "PASTURE", "x": 2, "y": 7}),
    ]
    farm_state = make_test_farm(day=3, structures=sw_pastures)
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    # Existing is 9, dynamic capacity should include existing + positive candidates, capped at HERD_CAP
    assert eval_result["existing_pastures"] == 9
    assert eval_result["dynamic_max_pastures"] >= 10
    assert eval_result["dynamic_max_pastures"] <= HERD_CAP


def test_case_b_old_sw_list_not_a_hard_cap():
    """All 9 SW positions blocked or occupied, NE/NW candidates qualify."""
    sw_blocked = [(x, y, {"kind": "PASTURE", "x": x, "y": y}) for x in range(3) for y in range(5, 8)]
    farm_state = make_test_farm(day=3, structures=sw_blocked)
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    positive_cands = eval_result["positive_candidates"]

    # Must contain candidates from NW or NE
    quadrants = {c["quadrant"] for c in positive_cands}
    assert any(q in ("NW", "NE") for q in quadrants)
    assert eval_result["dynamic_max_pastures"] > 9


def test_case_c_distance_ranking():
    """Distance 1 ranks before distance 5 (holding other factors constant)."""
    farm_state = make_test_farm(day=3)
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    positive = eval_result["positive_candidates"]
    assert len(positive) >= 2

    # Group non-seed candidates and verify distance monotonic ordering
    non_seed_cands = [c for c in positive if not c["is_preferred_early"] and not c["is_preferred_sw"]]
    for i in range(len(non_seed_cands) - 1):
        assert non_seed_cands[i]["distance_to_shed"] <= non_seed_cands[i+1]["distance_to_shed"]


def test_case_d_crop_opportunity_rejection():
    """Very high crop opportunity value rejects pasture candidates."""
    farm_state = make_test_farm(day=3)
    # Give extreme crop price so crop opportunity value exceeds livestock profit
    fc = FakeForecast({"CARROT": 2000.0, "POTATO": 2500.0, "MELON": 5000.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    assert len(eval_result["positive_candidates"]) == 0
    # Dynamic capacity should be only existing pastures (0)
    assert eval_result["dynamic_max_pastures"] == 0


def test_case_e_positive_livestock_conversion():
    """On Day 3 with moderate crop prices, viable near-shed candidates are accepted."""
    farm_state = make_test_farm(day=3)
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    assert len(eval_result["positive_candidates"]) > 0
    assert eval_result["dynamic_max_pastures"] > 0


def test_case_f_feed_cap_remains_binding():
    """get_animal_targets clamps to max_sustainable feed cap."""
    targets = get_animal_targets(
        day=3,
        money=5000.0,
        shed_wheat=50,
        current_animals={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        max_pastures=15,
        max_sustainable=4,
    )
    total_animals = sum(targets.values())
    assert total_animals <= 4


def test_case_g_herd_cap_remains_binding():
    """HERD_CAP=20 remains an absolute upper bound on dynamic pasture capacity."""
    farm_state = make_test_farm(day=3)
    fc = FakeForecast({"CARROT": 1.0, "POTATO": 1.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    assert eval_result["dynamic_max_pastures"] <= HERD_CAP


def test_case_h_locked_quadrants_ignored():
    """Tiles in locked quadrants (e.g. SE) are never pasture candidates."""
    farm_state = make_test_farm(day=3, unlocked=("NW", "SW"))
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    for c in eval_result["all_candidates"]:
        x, y = c["pos"]
        assert not (x >= 5 and y >= 5), f"SE tile {c['pos']} must not be evaluated when locked"
        assert c["quadrant"] in ("NW", "SW")


def test_case_i_shed_access_tiles_protected():
    """SHED_ACCESS_TILES and PORT_SW are strictly excluded from candidates."""
    farm_state = make_test_farm(day=3, unlocked=("NW", "SW", "NE", "SE"))
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    candidate_positions = {c["pos"] for c in eval_result["all_candidates"]}

    for access_pos in SHED_ACCESS_TILES:
        assert access_pos not in candidate_positions, f"Shed access tile {access_pos} must be excluded"
    assert PORT_SW not in candidate_positions, f"PORT_SW {PORT_SW} must be excluded"


def test_case_j_live_crops_not_destroyed():
    """Tiles with live crops are never evaluated or selected as pasture candidates."""
    crops = [
        (0, 5, "WHEAT"),
        (0, 6, "CARROT"),
        (1, 5, "POTATO"),
        (3, 4, "MELON"),
    ]
    farm_state = make_test_farm(day=3, crops=crops)
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0})

    eval_result = _eval_helper(farm_state, fc, day=3)
    candidate_positions = {c["pos"] for c in eval_result["all_candidates"]}

    for (cx, cy, _) in crops:
        assert (cx, cy) not in candidate_positions, f"Tile with live crop {(cx, cy)} must not be a pasture candidate"


def test_case_k_only_queued_build_tiles_removed_from_crop_queue():
    """Unbuilt SW tiles remain available for planting; only queued build tiles are reserved."""
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    farm = {
        "money": 5000.0,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4]],
        "unlocked_quadrants": ["NW", "SW", "NE"],
        "hires_today": 0,
    }
    obs = {
        "player": 0,
        "day": 3,
        "hour": 0,
        "farms": [farm, farm],
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
        "private": {
            "shed": {"WHEAT": 50, "MILK": 0, "WOOL": 0, "FERTILIZER": 0},
            "seeds": {},
            "inventories": [{}],
        },
    }
    ctx = parse_observation(obs)
    fc = FakeForecast({"CARROT": 20.0, "POTATO": 25.0, "WHEAT": 25.0})
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    queued_builds = set(plan.build_queue)
    plant_positions = {pos for pos, _ in plan.plant_queue}

    # Queued builds and plant positions must be strictly disjoint
    assert queued_builds.isdisjoint(plant_positions), "Build reservations must not overlap with crop planting allocations"
    # Unbuilt SW tiles outside queued builds must be eligible for crops
    sw_plantings = [pos for pos in plant_positions if pos[0] < 5 and pos[1] >= 5]
    assert len(sw_plantings) > 0, "Unbuilt SW tiles should be available for crop allocation"
