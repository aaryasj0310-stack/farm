"""Regression tests for crop planted_day vs animal placed_day accounting.

These tests intentionally exercise the timestamp boundary without changing feed,
livestock, land, or crop strategy.
"""
from types import SimpleNamespace

from state.observation_parser import animal_production_days
from strategy.feed_feasibility import collect_secured_wheat_deliveries
from strategy.macro_planner import compute_authoritative_feed_capacity


class TinyFarm:
    def __init__(self, tiles, money=450.0, unlocked=("NW",)):
        self._tiles = list(tiles)
        self.money = float(money)
        self.unlocked = set(unlocked)

    def iter_tiles(self):
        return iter(self._tiles)

    def quadrant_of(self, _pos):
        return "NW"


def wheat_tile(planted_day, *, placed_day=None, fertilized_until_day=-1, yield_units=0, pos=(0, 0)):
    return SimpleNamespace(
        kind="PLANT",
        is_plant=True,
        is_animal=False,
        crop="WHEAT",
        animal=None,
        planted_day=planted_day,
        placed_day=placed_day,
        fertilized_until_day=fertilized_until_day,
        yield_units=yield_units,
        pos=pos,
    )


def _days(tiles, current_day, end_day):
    return [
        (d.day, d.units)
        for d in collect_secured_wheat_deliveries(TinyFarm(tiles), current_day, end_day)
    ]


def test_a_newly_planted_wheat_not_immediately_credited():
    assert _days([wheat_tile(10)], current_day=10, end_day=13) == []


def test_b_partially_grown_wheat_keeps_true_age():
    assert _days([wheat_tile(7)], current_day=10, end_day=11) == [(11, 4)]


def test_c_max_yield_ready_wheat_arrives_today():
    assert _days([wheat_tile(6)], current_day=10, end_day=10) == [(10, 4)]


def test_d_crop_uses_planted_day_not_placed_day():
    # If the obsolete field were used, this would be projected for day 14.
    assert _days(
        [wheat_tile(7, placed_day=10)],
        current_day=10,
        end_day=11,
    ) == [(11, 4)]


def test_e_multiple_wheat_cohorts_keep_separate_delivery_days():
    tiles = [
        wheat_tile(6, pos=(0, 0)),
        wheat_tile(7, pos=(1, 0)),
        wheat_tile(8, pos=(2, 0)),
    ]
    assert _days(tiles, current_day=8, end_day=12) == [(10, 4), (11, 4), (12, 4)]


def test_f_animals_continue_to_use_placed_day():
    goose = SimpleNamespace(animal="GOOSE", placed_day=3)
    days = animal_production_days(goose)
    assert min(days) == 7  # GOOSE first_yield_day == 4
    assert 8 in days       # interval == 1


def test_g_standing_wheat_and_shed_wheat_are_not_double_counted():
    farm = TinyFarm([wheat_tile(8)], money=450.0)
    private = SimpleNamespace(shed={"WHEAT": 5}, inventories=[{}])
    info = compute_authoritative_feed_capacity(
        farm, private, day=10, season_end=12, current_animals_count=0
    )
    assert info["wheat_on_hand"] == 5
    assert info["planted_yield"] == 4
    assert info["affordable_wheat"] == 0
    assert info["projected_wheat_supply"] == 9


def test_h_unfertilized_tile_does_not_receive_fertilized_max_credit():
    normal = _days([wheat_tile(8)], current_day=10, end_day=12)
    fertilized = _days(
        [wheat_tile(8, fertilized_until_day=10)],
        current_day=10,
        end_day=12,
    )
    assert normal == [(12, 4)]
    assert fertilized == [(12, 6)]


def test_i_feed_horizon_boundary_is_exact():
    tile = wheat_tile(7)  # conservative max-yield arrival day = 11
    assert _days([tile], current_day=10, end_day=10) == []
    assert _days([tile], current_day=10, end_day=11) == [(11, 4)]


def test_missing_planted_day_gets_zero_future_credit():
    tile = wheat_tile(None, placed_day=7)
    assert _days([tile], current_day=10, end_day=20) == []


def test_j_real_engine_plant_schema_uses_planted_day_not_placed_day():
    from kaggle_environments.envs.kaggriculture.kaggriculture import (
        CROPS as ENGINE_CROPS,
        _new_plant,
    )

    raw = _new_plant("WHEAT", 3, 24)
    assert raw["planted_day"] == 3
    assert "placed_day" not in raw
    assert 3 + ENGINE_CROPS["WHEAT"]["first_yield_day"] == 5
    assert 3 + ENGINE_CROPS["WHEAT"]["max_yield_day"] == 7
