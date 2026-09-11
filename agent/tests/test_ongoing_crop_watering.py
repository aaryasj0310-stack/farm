"""Regression tests for labor-efficient ongoing crop (Tomato and Strawberry) watering policy.

Validates:
1. Tomato alternates watering outside fertilized production days.
2. Strawberry alternates watering outside fertilized production days.
3. Tomato with consecutive_unwatered == 1 is always watered.
4. Strawberry with consecutive_unwatered == 1 is always watered.
5. Tomato on a fertilized production day is watered.
6. Strawberry on a fertilized production day is watered.
7. Unfertilized production day may be skipped if parity says skip and survival is safe.
8. Planting-day watering remains mandatory.
9. Wheat/Carrot/Melon behavior is unchanged.
"""
import pytest

from observation_parser import needs_water_today, crop_produces_today, TileView


class MockTile:
    def __init__(self, x=0, y=0, crop="TOMATO", planted_day=0, watered_today=False,
                 consecutive_unwatered=0, fertilized_until_day=-1, kind="PLANT", yield_units=0):
        self.x = x
        self.y = y
        self.crop = crop
        self.planted_day = planted_day
        self.watered_today = watered_today
        self.consecutive_unwatered = consecutive_unwatered
        self.fertilized_until_day = fertilized_until_day
        self.kind = kind
        self.yield_units = yield_units
        self.is_plant = (kind == "PLANT")


def test_tomato_alternates_watering_outside_fertilized_production_days():
    """Tomato outside fertilized production days uses alternate-day checkerboard watering."""
    t00 = MockTile(x=0, y=0, crop="TOMATO", planted_day=0, fertilized_until_day=-1)
    assert needs_water_today(t00, day=1) is False
    assert needs_water_today(t00, day=2) is True
    assert needs_water_today(t00, day=3) is False
    assert needs_water_today(t00, day=4) is True

    t01 = MockTile(x=0, y=1, crop="TOMATO", planted_day=0, fertilized_until_day=-1)
    assert needs_water_today(t01, day=1) is True
    assert needs_water_today(t01, day=2) is False
    assert needs_water_today(t01, day=3) is True
    assert needs_water_today(t01, day=4) is False


def test_strawberry_alternates_watering_outside_fertilized_production_days():
    """Strawberry outside fertilized production days uses alternate-day checkerboard watering."""
    t00 = MockTile(x=0, y=0, crop="STRAWBERRY", planted_day=0, fertilized_until_day=-1)
    assert needs_water_today(t00, day=1) is False
    assert needs_water_today(t00, day=2) is True
    assert needs_water_today(t00, day=3) is False
    assert needs_water_today(t00, day=4) is True
    assert needs_water_today(t00, day=5) is False

    t01 = MockTile(x=0, y=1, crop="STRAWBERRY", planted_day=0, fertilized_until_day=-1)
    assert needs_water_today(t01, day=1) is True
    assert needs_water_today(t01, day=2) is False
    assert needs_water_today(t01, day=3) is True
    assert needs_water_today(t01, day=4) is False


def test_tomato_with_consecutive_unwatered_1_is_always_watered():
    """Tomato with consecutive_unwatered == 1 must be watered immediately regardless of parity."""
    t = MockTile(x=0, y=0, crop="TOMATO", planted_day=0, consecutive_unwatered=1, fertilized_until_day=-1)
    assert needs_water_today(t, day=1) is True
    assert needs_water_today(t, day=3) is True
    assert needs_water_today(t, day=5) is True


def test_strawberry_with_consecutive_unwatered_1_is_always_watered():
    """Strawberry with consecutive_unwatered == 1 must be watered immediately regardless of parity."""
    t = MockTile(x=0, y=0, crop="STRAWBERRY", planted_day=0, consecutive_unwatered=1, fertilized_until_day=-1)
    assert needs_water_today(t, day=1) is True
    assert needs_water_today(t, day=3) is True
    assert needs_water_today(t, day=7) is True


def test_tomato_on_fertilized_production_day_is_watered():
    """Tomato on a fertilized production day must be watered even if parity would skip."""
    t = MockTile(x=0, y=0, crop="TOMATO", planted_day=0, fertilized_until_day=15)
    assert crop_produces_today(t, day=7) is True
    assert crop_produces_today(t, day=8) is True
    assert needs_water_today(t, day=7) is True
    assert needs_water_today(t, day=8) is True


def test_strawberry_on_fertilized_production_day_is_watered():
    """Strawberry on a fertilized production day must be watered to double yield."""
    t = MockTile(x=0, y=0, crop="STRAWBERRY", planted_day=0, fertilized_until_day=20)
    assert crop_produces_today(t, day=9) is True
    assert crop_produces_today(t, day=10) is True
    assert needs_water_today(t, day=9) is True
    assert needs_water_today(t, day=11) is True


def test_unfertilized_production_day_skipped_if_parity_says_skip_and_survival_safe():
    """Unfertilized ongoing crop skips on a production day if parity says skip and survival is safe."""
    t_straw = MockTile(x=0, y=0, crop="STRAWBERRY", planted_day=0, fertilized_until_day=-1,
                       consecutive_unwatered=0)
    assert crop_produces_today(t_straw, day=9) is True
    assert needs_water_today(t_straw, day=9) is False

    t_tom = MockTile(x=0, y=0, crop="TOMATO", planted_day=0, fertilized_until_day=-1,
                     consecutive_unwatered=0)
    assert crop_produces_today(t_tom, day=7) is True
    assert needs_water_today(t_tom, day=7) is False


def test_planting_day_watering_remains_mandatory():
    """Planting day ALWAYS requires watering regardless of crop type, parity, or fertilizer."""
    t_tom = MockTile(x=0, y=0, crop="TOMATO", planted_day=1, consecutive_unwatered=0, fertilized_until_day=-1)
    assert needs_water_today(t_tom, day=1) is True

    t_straw = MockTile(x=0, y=0, crop="STRAWBERRY", planted_day=3, consecutive_unwatered=0, fertilized_until_day=-1)
    assert needs_water_today(t_straw, day=3) is True

    t_wheat = MockTile(x=0, y=0, crop="WHEAT", planted_day=5, consecutive_unwatered=0)
    assert needs_water_today(t_wheat, day=5) is True


def test_one_time_crops_behavior_unchanged():
    """Wheat/Carrot/Melon continue to water daily during bonus window and alternate otherwise."""
    t_wheat = MockTile(x=0, y=0, crop="WHEAT", planted_day=0, consecutive_unwatered=0)
    assert needs_water_today(t_wheat, day=1) is False
    assert needs_water_today(t_wheat, day=2) is True
    assert needs_water_today(t_wheat, day=3) is True
    assert needs_water_today(t_wheat, day=4) is True

    t_melon = MockTile(x=0, y=0, crop="MELON", planted_day=0, consecutive_unwatered=0)
    assert needs_water_today(t_melon, day=5) is False
    assert needs_water_today(t_melon, day=6) is True
    assert needs_water_today(t_melon, day=7) is True

    t_carrot = MockTile(x=0, y=0, crop="CARROT", planted_day=0, consecutive_unwatered=0)
    assert needs_water_today(t_carrot, day=1) is False
    assert needs_water_today(t_carrot, day=2) is True
    assert needs_water_today(t_carrot, day=3) is True
