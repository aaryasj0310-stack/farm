"""Tests for Phase M0-G Fertilizer Mechanics and Baseline Behavior."""
import pytest
import copy
import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kengine


def create_test_farm():
    return {
        "farmer": [0, 0],
        "hands": [],
        "tiles": [[None] * 10 for _ in range(10)],
    }


def create_test_private():
    return {
        "inventories": [{}],
        "shed": {},
        "seeds": {},
    }


def test_fertilizer_availability_resets_daily():
    """1. Fertilizer availability resets to True at EOD."""
    farm = create_test_farm()
    cow_tile = kengine._new_animal("COW", 0)
    cow_tile["fertilizer_available"] = False
    farm["tiles"][2][2] = cow_tile

    kengine._daily_refresh_animals(farm, 1)
    assert cow_tile["fertilizer_available"] is True


def test_fertilizer_non_accumulation():
    """2. Uncollected fertilizer does not accumulate beyond one opportunity."""
    farm = create_test_farm()
    cow_tile = kengine._new_animal("COW", 0)
    farm["tiles"][2][2] = cow_tile

    for day in range(1, 4):
        farm["tiles"][2][2]["fed_today"] = True
        kengine._daily_refresh_animals(farm, day)
        assert farm["tiles"][2][2]["fertilizer_available"] is True
        assert isinstance(farm["tiles"][2][2]["fertilizer_available"], bool)


def test_collect_gives_exactly_one_fertilizer():
    """3. COLLECT gives exactly one fertilizer."""
    farm = create_test_farm()
    farm["farmer"] = [2, 2]
    private = create_test_private()

    cow_tile = kengine._new_animal("COW", 0)
    cow_tile["fertilizer_available"] = True
    farm["tiles"][2][2] = cow_tile

    kengine._apply_unit_action(farm, private, 0, ["COLLECT_FERTILIZER"], 10, 0, 24)
    assert cow_tile["fertilizer_available"] is False
    assert private["inventories"][0].get("FERTILIZER") == 1


def test_skipping_collect_does_not_affect_survival():
    """4. Skipping COLLECT does not affect animal survival."""
    farm = create_test_farm()
    cow_tile = kengine._new_animal("COW", 0)
    farm["tiles"][2][2] = cow_tile

    # Feed animal daily, never collect fertilizer
    for day in range(1, 10):
        cow_tile["fed_today"] = True
        kengine._daily_refresh_animals(farm, day)
        assert cow_tile["consecutive_unfed"] == 0
        assert "animal" in farm["tiles"][2][2]


def test_skipping_collect_does_not_affect_production():
    """5. Skipping COLLECT does not affect animal production."""
    farm = create_test_farm()
    cow1 = kengine._new_animal("COW", 0)
    cow2 = kengine._new_animal("COW", 0)
    farm["tiles"][2][2] = cow1
    farm["tiles"][2][3] = cow2

    private = create_test_private()

    for day in range(1, 10):
        cow1["fed_today"] = True
        cow1["cared_today"] = True
        cow2["fed_today"] = True
        cow2["cared_today"] = True

        # Collect only from cow1
        if cow1["fertilizer_available"]:
            farm["farmer"] = [2, 2]
            kengine._apply_unit_action(farm, private, 0, ["COLLECT_FERTILIZER"], 10, day, 24)

        kengine._daily_refresh_animals(farm, day)

        assert cow1["yield_units"] == cow2["yield_units"]
        assert cow1.get("pending_care_bonus", 0) == cow2.get("pending_care_bonus", 0)


def test_off_reproduces_historical_behavior():
    """6. Baseline configuration preserves historical behavior."""
    import config
    assert config.SAME_TURN_DEPOSIT_SELL_MODE == "BASELINE"
    assert config.MIDNIGHT_STORAGE_DUMP_MODE == "OFF"
    assert config.ANIMAL_SERVICE_ECONOMICS_MODE == "OFF"
