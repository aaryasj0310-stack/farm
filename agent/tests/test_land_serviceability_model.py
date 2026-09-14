"""Unit tests for land serviceability model and partial SW exploitation."""
import pytest
from unittest.mock import MagicMock
from config import (
    SW_SOIL_TILES,
    get_target_hands,
    EFFECTIVE_ACTIONS_PER_UNIT,
    set_sw_force_k_tiles,
    SW_FORCE_K_TILES,
)
from strategy.land_serviceability_model import (
    compute_daily_labor_capacity,
    compute_existing_workload,
    compute_candidate_sw_workload,
    evaluate_sw_serviceability,
    get_sorted_sw_soil_tiles,
    SHED_POS,
)
from strategy.macro_planner import sw_plant_decision
from strategy.expansion_planner import should_buy_land


def test_daily_labor_capacity():
    """Verify effective labor capacity matches empirical 12 actions/unit/day."""
    for day in (0, 5, 10, 15, 20):
        cap = compute_daily_labor_capacity(day, safety_margin=0.15)
        planned_hands = get_target_hands(day)
        expected_raw = (1 + planned_hands) * EFFECTIVE_ACTIONS_PER_UNIT
        expected_reserve = round(expected_raw * 0.15, 1)
        expected_usable = expected_raw - expected_reserve

        assert cap["planned_hands"] == planned_hands
        assert cap["worker_count"] == 1 + planned_hands
        assert cap["raw_effective_capacity"] == expected_raw
        assert cap["safety_reserve_actions"] == expected_reserve
        assert cap["usable_effective_actions"] == expected_usable


def test_sorted_sw_soil_tiles():
    """Verify SW soil tiles are 15 coordinates sorted by Manhattan distance to shed."""
    sorted_tiles = get_sorted_sw_soil_tiles()
    assert len(sorted_tiles) == 15
    assert set(sorted_tiles) == SW_SOIL_TILES

    dists = [abs(p[0] - SHED_POS[0]) + abs(p[1] - SHED_POS[1]) for p in sorted_tiles]
    assert dists == sorted(dists), "Tiles must be sorted ascending by distance to shed"


def test_candidate_sw_workload():
    """Verify candidate SW workloads increase monotonically with k and include travel overhead."""
    wl5 = compute_candidate_sw_workload(5, 12)
    wl10 = compute_candidate_sw_workload(10, 12)
    wl15 = compute_candidate_sw_workload(15, 12)

    assert wl5["sw_total_effective_workload"] < wl10["sw_total_effective_workload"]
    assert wl10["sw_total_effective_workload"] < wl15["sw_total_effective_workload"]
    assert wl5["sw_travel_burden"] > 0
    assert wl15["sw_travel_burden"] > wl5["sw_travel_burden"]


def test_existing_workload_mock_farm():
    """Verify existing workload calculation on NW and NE tiles."""
    farm = MagicMock()
    farm.unlocked = ["NW", "NE"]

    class MockTile:
        def __init__(self, pos, is_plant=False, is_animal=False, crop=None, watered=False,
                     consecutive_unwatered=0, yield_units=0, fed=False):
            self.pos = pos
            self.is_plant = is_plant
            self.is_animal = is_animal
            self.crop = crop
            self.watered_today = watered
            self.consecutive_unwatered = consecutive_unwatered
            self.yield_units = yield_units
            self.fed_today = fed
            self.kind = "PLANT" if is_plant else ("ANIMAL" if is_animal else "SOIL")
            self.is_fallow = not (is_plant or is_animal)

    def mock_quadrant(pos):
        x, y = pos
        if x < 5 and y < 5: return "NW"
        if x >= 5 and y < 5: return "NE"
        if x < 5 and y >= 5: return "SW"
        return "SE"

    farm.quadrant_of.side_effect = mock_quadrant

    tiles = [
        # NW: 2 plants needing water, 1 urgent harvest
        MockTile((1, 1), is_plant=True, crop="WHEAT", watered=False, consecutive_unwatered=1),
        MockTile((1, 2), is_plant=True, crop="MELON", watered=False, consecutive_unwatered=0),
        MockTile((1, 3), is_plant=True, crop="CARROT", watered=True, yield_units=4),
        # NE: 1 unfed animal
        MockTile((6, 1), is_animal=True, fed=False),
        # SW: should NOT count towards NW/NE existing workload
        MockTile((1, 6), is_plant=True, crop="CARROT", watered=False),
    ]
    farm.iter_tiles.return_value = tiles

    wl = compute_existing_workload(farm, day=10)
    assert wl["nw_workload"] >= 2.0
    assert wl["ne_workload"] == 1.0
    assert wl["total_existing_workload"] >= 3.0


def test_evaluate_sw_serviceability_dynamic():
    """Verify dynamic SW serviceability returns positive best_k when workforce is sufficient."""
    farm = MagicMock()
    farm.unlocked = ["NW", "NE"]
    farm.iter_tiles.return_value = []
    farm.quadrant_of.return_value = "NW"

    is_serv, best_k, diag = evaluate_sw_serviceability(
        current_day=12, farm=farm, money=10000.0, forecast=None, target_quadrant=3
    )
    assert is_serv is True
    assert best_k in (5, 10, 15, 18, 21, 24)
    assert diag["is_serviceable"] is True
    assert diag["net_marginal_profit"] > 0
    assert diag["expected_nw_ne_opportunity_cost"] == 0.0


def test_evaluate_sw_serviceability_forced_k():
    """Verify forcing k in {5, 10, 15} respects the forced constraint."""
    farm = MagicMock()
    farm.unlocked = ["NW", "NE"]
    farm.iter_tiles.return_value = []
    farm.quadrant_of.return_value = "NW"

    for k in (5, 10, 15):
        set_sw_force_k_tiles(k)
        is_serv, best_k, diag = evaluate_sw_serviceability(
            current_day=12, farm=farm, money=10000.0, forecast=None, target_quadrant=3
        )
        assert best_k == k
    set_sw_force_k_tiles(None)


def test_sw_plant_decision_with_max_tiles():
    """Verify sw_plant_decision respects max_tiles parameter."""
    dec = sw_plant_decision(day=9, free_tiles=15, wheat_stock=10, herd_size=6, max_tiles=5)
    total_seeds = dec["WHEAT"] + dec["CARROT"]
    assert total_seeds <= 5

    dec26 = sw_plant_decision(day=26, free_tiles=15, wheat_stock=0, herd_size=9, max_tiles=10)
    assert dec26["WHEAT"] == 0
    assert dec26["CARROT"] == 10


def test_should_buy_land_sw_integration():
    """Verify should_buy_land integrates serviceability diagnostics."""
    farm = MagicMock()
    farm.unlocked = ["NW", "NE"]
    farm.hands = [MagicMock() for _ in range(12)]
    farm.iter_tiles.return_value = []
    farm.quadrant_of.return_value = "NW"

    set_sw_force_k_tiles(None)
    ok, reason, diag = should_buy_land(
        next_quadrant=3,
        current_day=12,
        money=10000.0,
        farm=farm,
        hire_cost=200.0,
        feed_cost=0.0,
        animal_cost=0.0,
        reserve=200.0,
        roi=2.0,
        ow_factor=1.0,
    )
    assert "labor_serviceability_result" in diag
    assert "best_k_tiles" in diag
    assert "net_marginal_profit" in diag
    assert "serviceability_adjusted_roi" in diag
    assert "expected_nw_ne_opportunity_cost" in diag
