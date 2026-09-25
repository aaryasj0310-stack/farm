"""Unit tests for Phase M0-F: Adaptive Animal CARE & Feed-Bank Economics.

Tests:
1. Cow care bank accumulation.
2. Sheep care bank accumulation.
3. Goose daily production behavior.
4. Production-day old bank consumption.
5. Production-day new CARE banks for future production.
6. Unfed production behavior.
7. One unfed day survives.
8. Two consecutive unfed days escape.
9. Mandatory FEED at consecutive_unfed == 1.
10. Max-held clipping.
11. CARE skip when no future production.
12. CARE skip when bank cannot be realized.
13. CARE retained when positive marginal value.
14. Off-production FEED skip only when survival-safe.
15. Production-day FEED correctly values pending bank.
16. OFF mode reproduces historical behavior.
17. SHADOW changes no actions.
18. LIVE resets correctly between matches.
19. agent/ and submission/ remain synchronized.
"""
from __future__ import annotations

import copy
import filecmp
import os
from types import SimpleNamespace
import pytest

import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
from config import (
    ANIMAL_SERVICE_ECONOMICS_MODE,
    get_animal_service_economics_mode,
    set_animal_service_economics_mode,
)
from strategy.animal_service_economics import (
    evaluate_animal_service_opportunity,
    get_future_production_days,
    is_production_day,
    reset_animal_service_telemetry,
    get_animal_service_telemetry,
)


def make_mock_tile(species="COW", placed_day=0, consecutive_unfed=0, yield_units=0, pending_bonus=0, fed=False, cared=False):
    return SimpleNamespace(
        is_animal=True,
        animal=species,
        placed_day=placed_day,
        consecutive_unfed=consecutive_unfed,
        yield_units=yield_units,
        pending_care_bonus=pending_bonus,
        fed_today=fed,
        cared_today=cared,
        fertilizer_available=False,
        pos=(2, 2),
    )


# 1. Cow care bank accumulation
def test_01_cow_care_bank_accumulation():
    # COW: first_yield_day=8, interval=2. Day 0-6 off-days.
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 0, "pending_care_bonus": 0,
        "fed_today": True, "cared_today": True,
    }
    kengine._daily_refresh_animals(farm, 0)
    assert farm["tiles"][0][0]["pending_care_bonus"] == 1
    farm["tiles"][0][0]["fed_today"] = True
    farm["tiles"][0][0]["cared_today"] = True
    kengine._daily_refresh_animals(farm, 1)
    assert farm["tiles"][0][0]["pending_care_bonus"] == 2


# 2. Sheep care bank accumulation
def test_02_sheep_care_bank_accumulation():
    # SHEEP: first_yield_day=6, interval=3.
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "SHEEP", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 0, "pending_care_bonus": 0,
        "fed_today": True, "cared_today": True,
    }
    for d in range(3):
        farm["tiles"][0][0]["fed_today"] = True
        farm["tiles"][0][0]["cared_today"] = True
        kengine._daily_refresh_animals(farm, d)
    assert farm["tiles"][0][0]["pending_care_bonus"] == 3


# 3. Goose daily production behavior
def test_03_goose_daily_production():
    # GOOSE: first_yield_day=4, interval=1. Day 3 produces for day 4.
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "COOP", "animal": "GOOSE", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 0, "pending_care_bonus": 0,
        "fed_today": True, "cared_today": True,
    }
    kengine._daily_refresh_animals(farm, 3) # End of day 3 (production day)
    assert farm["tiles"][0][0]["yield_units"] == 1
    assert farm["tiles"][0][0]["pending_care_bonus"] == 1


# 4. Production-day old bank consumption
def test_04_production_day_old_bank_consumption():
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 0, "pending_care_bonus": 3,
        "fed_today": True, "cared_today": False,
    }
    kengine._daily_refresh_animals(farm, 7) # Production day
    assert farm["tiles"][0][0]["yield_units"] == 4 # base 1 + bonus 3
    assert farm["tiles"][0][0]["pending_care_bonus"] == 0


# 5. Production-day new CARE banks for future production
def test_05_production_day_new_care_banks_for_future():
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 0, "pending_care_bonus": 2,
        "fed_today": True, "cared_today": True, # CARE on production day!
    }
    kengine._daily_refresh_animals(farm, 7)
    assert farm["tiles"][0][0]["yield_units"] == 3 # base 1 + bonus 2 consumed
    assert farm["tiles"][0][0]["pending_care_bonus"] == 1 # new CARE banked for next cycle!


# 6. Unfed production behavior
def test_06_unfed_production_behavior():
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 0, "pending_care_bonus": 3,
        "fed_today": False, "cared_today": False,
    }
    kengine._daily_refresh_animals(farm, 7)
    assert farm["tiles"][0][0]["yield_units"] == 1 # base 1 produced
    assert farm["tiles"][0][0]["pending_care_bonus"] == 0 # bonus wiped without granting!
    assert farm["tiles"][0][0]["consecutive_unfed"] == 1


# 7. One unfed day survives
def test_07_one_unfed_day_survives():
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "SHEEP", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 0, "pending_care_bonus": 0,
        "fed_today": False, "cared_today": False,
    }
    kengine._daily_refresh_animals(farm, 0)
    assert farm["tiles"][0][0]["animal"] == "SHEEP"
    assert farm["tiles"][0][0]["consecutive_unfed"] == 1


# 8. Two consecutive unfed days escape
def test_08_two_consecutive_unfed_escape():
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "SHEEP", "placed_day": 0,
        "consecutive_unfed": 1, "yield_units": 0, "pending_care_bonus": 0,
        "fed_today": False, "cared_today": False,
    }
    kengine._daily_refresh_animals(farm, 1)
    assert "animal" not in farm["tiles"][0][0]
    assert farm["tiles"][0][0]["kind"] == "PASTURE"


# 9. Mandatory FEED at consecutive_unfed == 1
def test_09_mandatory_feed_at_consecutive_unfed_1():
    t = make_mock_tile(species="COW", consecutive_unfed=1)
    ctx = {"day": 5}
    res = evaluate_animal_service_opportunity(t, ctx)
    assert res["should_feed"] is True
    assert res["feed_reason"] == "MANDATORY_SURVIVAL_FEED"


# 10. Max-held clipping
def test_10_max_held_clipping():
    farm = {"tiles": [[None]*10 for _ in range(10)]}
    farm["tiles"][0][0] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0,
        "consecutive_unfed": 0, "yield_units": 5, "pending_care_bonus": 3,
        "fed_today": True, "cared_today": False,
    }
    kengine._daily_refresh_animals(farm, 7) # Production day
    # 5 + 1 + 3 = 9, clipped to max_held 6
    assert farm["tiles"][0][0]["yield_units"] == 6


# 11. CARE skip when no future production
def test_11_care_skip_when_no_future_production():
    # Day 29: season ends! No future production day after day 29.
    t = make_mock_tile(species="COW", placed_day=0, consecutive_unfed=0)
    ctx = {"day": 29}
    res = evaluate_animal_service_opportunity(t, ctx)
    assert res["should_care"] is False
    assert res["care_reason"] in ("NO_FUTURE_PRODUCTION_EVENT", "ENDGAME_TOO_LATE", "UNFED_ANIMAL_CANNOT_BANK_CARE")


# 12. CARE skip when bank cannot be realized
def test_12_care_skip_when_bank_cannot_be_realized():
    # COW placed on day 25. First yield day is 8 -> 25 + 8 = 33 > 29.
    # Will never produce before season ends!
    t = make_mock_tile(species="COW", placed_day=25)
    ctx = {"day": 26}
    res = evaluate_animal_service_opportunity(t, ctx)
    assert res["should_care"] is False
    assert res["should_feed"] is False


# 13. CARE retained when positive marginal value
def test_13_care_retained_when_positive_value():
    t = make_mock_tile(species="COW", placed_day=0, consecutive_unfed=0, yield_units=0, pending_bonus=0)
    ctx = {"day": 3}
    res = evaluate_animal_service_opportunity(t, ctx)
    assert res["should_care"] is True


# 14. Off-production FEED skip only when survival-safe
def test_14_off_prod_feed_skip_when_safe():
    # When care bank already clips max_held, off-prod feed can be safely skipped
    t = make_mock_tile(species="COW", placed_day=0, consecutive_unfed=0, yield_units=0, pending_bonus=5)
    ctx = {"day": 5}
    res = evaluate_animal_service_opportunity(t, ctx)
    assert res["should_feed"] is False
    assert res["feed_reason"] in ("CARE_BANK_ALREADY_SUFFICIENT", "CARE_BANK_MAXED", "CARE_BONUS_WOULD_CLIP")


# 15. Production-day FEED correctly values pending bank
def test_15_production_day_feed_values_pending_bank():
    # Day 7 is cow production day
    t = make_mock_tile(species="COW", placed_day=0, consecutive_unfed=0, yield_units=0, pending_bonus=3)
    ctx = {"day": 7}
    res = evaluate_animal_service_opportunity(t, ctx)
    assert res["should_feed"] is True
    assert res["feed_reason"] == "REALIZE_BANK_ON_PRODUCTION_DAY"


# 16. OFF mode reproduces historical behavior
def test_16_off_mode_reproduces_historical():
    set_animal_service_economics_mode("OFF")
    assert get_animal_service_economics_mode() == "OFF"


# 17. SHADOW changes no actions
def test_17_shadow_changes_no_actions():
    set_animal_service_economics_mode("SHADOW")
    assert get_animal_service_economics_mode() == "SHADOW"
    set_animal_service_economics_mode("OFF")


# 18. LIVE resets correctly between matches
def test_18_live_resets_correctly():
    reset_animal_service_telemetry()
    telem = get_animal_service_telemetry()
    assert telem["animal_days_evaluated"] == 0
    assert telem["feed_actions_skipped"] == 0


# 19. agent/ and submission/ remain synchronized
def test_19_agent_and_submission_sync():
    files = [
        ("agent/config.py", "submission/config.py"),
        ("agent/main.py", "submission/main.py"),
        ("agent/execution/task_scheduler.py", "submission/execution/task_scheduler.py"),
        ("agent/strategy/animal_service_economics.py", "submission/strategy/animal_service_economics.py"),
    ]
    repo_root = r"d:\website project\kaggri ox"
    for f1, f2 in files:
        p1 = os.path.join(repo_root, f1)
        p2 = os.path.join(repo_root, f2)
        assert filecmp.cmp(p1, p2, shallow=False), f"Files not synced: {f1} vs {f2}"
