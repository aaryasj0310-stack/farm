"""Unit tests for AnimalSurvivalTracker in Phase SW-B2-R1.

Tests verify:
1. Continuous survival: animals fed daily pass all rollover reconciliations with zero losses.
2. Single missed feed recovery: animal unfed for 1 day, fed the next day, resets consecutive_unfed.
3. Confirmed starvation death: animal unfed for 2 consecutive days disappears across midnight rollover and is flagged.
4. Ambiguous disappearance: animal disappears or mutates without consecutive_unfed justification and is flagged.
5. Feed floor monitoring: correctly detects and records wheat buffer drops below safe floor max(10, animals * 2).
"""
import copy
import os
import sys
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_AGENT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [_ROOT, _AGENT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.diagnostics.animal_tracker import AnimalSurvivalTracker


def _make_mock_obs(
    day: int,
    hour: int,
    animal_tile: dict = None,
    shed_wheat: int = 20,
    carried_wheat: int = 0,
    board_size: int = 10,
    seat: int = 0,
) -> dict:
    tiles = [[None for _ in range(board_size)] for _ in range(board_size)]
    if animal_tile is not None:
        tiles[2][2] = copy.deepcopy(animal_tile)

    farm = {"tiles": tiles, "money": 5000}
    farms = [farm, {"tiles": copy.deepcopy(tiles), "money": 5000}]
    private = {
        "shed": {"WHEAT": shed_wheat},
        "inventories": [{"WHEAT": carried_wheat}],
    }
    return {
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": farms,
        "private": private,
    }


def test_continuous_healthy_survival():
    """Test 1: Healthy animal fed daily survives across midnight rollovers."""
    tracker = AnimalSurvivalTracker(seat=0)

    # Day 5, Hours 20 to 23: animal fed
    for h in range(20, 24):
        obs = _make_mock_obs(
            day=5,
            hour=h,
            animal_tile={"kind": "PASTURE", "animal": "COW", "consecutive_unfed": 0, "fed_today": True},
            shed_wheat=25,
        )
        tracker.observe_turn(obs)

    # Day 6, Hour 0: post-rollover
    obs_next = _make_mock_obs(
        day=6,
        hour=0,
        animal_tile={"kind": "PASTURE", "animal": "COW", "consecutive_unfed": 0, "fed_today": False},
        shed_wheat=25,
    )
    tracker.observe_turn(obs_next)

    summary = tracker.get_summary()
    assert summary["total_animal_losses"] == 0
    assert summary["confirmed_starvation_deaths"] == 0
    assert summary["rollover_reconciliations_count"] == 1
    assert summary["continuous_feed_floor_preserved"] is True


def test_single_unfed_day_recovery():
    """Test 2: Animal missed feed on Day 5 (consecutive_unfed becomes 1), survives into Day 6."""
    tracker = AnimalSurvivalTracker(seat=0)

    # Day 5 Hour 23: not fed today
    obs_d5_h23 = _make_mock_obs(
        day=5,
        hour=23,
        animal_tile={"kind": "PASTURE", "animal": "COW", "consecutive_unfed": 0, "fed_today": False},
        shed_wheat=25,
    )
    tracker.observe_turn(obs_d5_h23)
    assert tracker.missed_feeding_days == 1

    # Day 6 Hour 0: post-rollover, consecutive_unfed is now 1 (engine increments it), animal still alive
    obs_d6_h0 = _make_mock_obs(
        day=6,
        hour=0,
        animal_tile={"kind": "PASTURE", "animal": "COW", "consecutive_unfed": 1, "fed_today": False},
        shed_wheat=25,
    )
    tracker.observe_turn(obs_d6_h0)

    summary = tracker.get_summary()
    assert summary["total_animal_losses"] == 0
    assert summary["confirmed_starvation_deaths"] == 0
    assert summary["rollover_reconciliations_count"] == 1


def test_confirmed_starvation_death_across_rollover():
    """Test 3: Animal with consecutive_unfed=1 not fed on Day 6 dies at midnight rollover to Day 7."""
    tracker = AnimalSurvivalTracker(seat=0)

    # Day 6 Hour 23: consecutive_unfed=1 and fed_today=False
    obs_d6_h23 = _make_mock_obs(
        day=6,
        hour=23,
        animal_tile={"kind": "PASTURE", "animal": "COW", "consecutive_unfed": 1, "fed_today": False},
        shed_wheat=25,
    )
    tracker.observe_turn(obs_d6_h23)

    # Day 7 Hour 0: Engine replaces animal with empty pasture: {"kind": "PASTURE"}
    obs_d7_h0 = _make_mock_obs(
        day=7,
        hour=0,
        animal_tile={"kind": "PASTURE"},  # 'animal' key removed by engine!
        shed_wheat=25,
    )
    tracker.observe_turn(obs_d7_h0)

    summary = tracker.get_summary()
    assert summary["confirmed_starvation_deaths"] == 1
    assert summary["total_animal_losses"] == 1
    assert len(summary["loss_events"]) == 1
    assert summary["loss_events"][0]["type"] == "CONFIRMED_STARVATION_DEATH"
    assert summary["loss_events"][0]["species"] == "COW"


def test_ambiguous_disappearance_flagged():
    """Test 4: Animal disappears when it was properly fed (unexpected loss/bug) is flagged."""
    tracker = AnimalSurvivalTracker(seat=0)

    # Day 8 Hour 23: fed_today=True, consecutive_unfed=0
    obs_d8_h23 = _make_mock_obs(
        day=8,
        hour=23,
        animal_tile={"kind": "PASTURE", "animal": "SHEEP", "consecutive_unfed": 0, "fed_today": True},
        shed_wheat=25,
    )
    tracker.observe_turn(obs_d8_h23)

    # Day 9 Hour 0: Tile is suddenly None
    obs_d9_h0 = _make_mock_obs(
        day=9,
        hour=0,
        animal_tile=None,
        shed_wheat=25,
    )
    tracker.observe_turn(obs_d9_h0)

    summary = tracker.get_summary()
    assert summary["ambiguous_disappearances"] == 1
    assert summary["total_animal_losses"] == 1
    assert summary["loss_events"][0]["type"] == "AMBIGUOUS_DISAPPEARANCE"


def test_feed_floor_breach_detection():
    """Test 5: Tracker detects and records turns when feed wheat drops below safe reserve."""
    tracker = AnimalSurvivalTracker(seat=0)

    # 1 Cow -> safe_feed_reserve = max(10, 1 * 2) = 10 wheat
    # But shed has only 6 wheat, carried has 0 -> deficit of 4 wheat!
    obs_breach = _make_mock_obs(
        day=10,
        hour=12,
        animal_tile={"kind": "PASTURE", "animal": "COW", "consecutive_unfed": 0, "fed_today": True},
        shed_wheat=6,
        carried_wheat=0,
    )
    tracker.observe_turn(obs_breach)

    summary = tracker.get_summary()
    assert summary["feed_floor_breach_turns"] == 1
    assert summary["continuous_feed_floor_preserved"] is False
    assert summary["min_total_feed_wheat_observed"] == 6
    assert len(summary["loss_events"]) == 0  # No deaths, but feed floor breached
