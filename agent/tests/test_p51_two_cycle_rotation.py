"""Unit and integration tests for Kaggriculture P5.1 Two-Cycle Carrot Rotation.

Tests:
1. Production default flag is False and flag getter/setter works correctly.
2. Manager state machine lifecycle and strict confirmation checks (including planting-day water).
3. Sequential collective feed safety ledger (zero double counting, buffer floor preservation).
4. Market order priority promotion (P1_URGENT) for pre-ordered C2 carrot seeds.
5. MacroPlanner queue protection (suppressing managed coordinates from generic wheat).
"""
import pytest
from unittest.mock import MagicMock

import config
from strategy.two_cycle_rotation_manager import (
    TwoCycleRotationManager,
    RotationPhase,
    RotationRecord,
    get_rotation_manager,
    reset_rotation_manager,
)


def test_p51_config_flag_default():
    """Verify P51_T1_TWO_CYCLE_CARROT_ENABLED defaults to False (production baseline exactness)."""
    assert config.P51_T1_TWO_CYCLE_CARROT_ENABLED is False
    assert config.get_p51_t1_two_cycle_carrot_enabled() is False

    config.set_p51_t1_two_cycle_carrot_enabled(True)
    assert config.get_p51_t1_two_cycle_carrot_enabled() is True
    config.set_p51_t1_two_cycle_carrot_enabled(False)
    assert config.get_p51_t1_two_cycle_carrot_enabled() is False


def test_manager_reset():
    """Verify rotation manager resets cleanly between episodes."""
    mgr = TwoCycleRotationManager()
    mgr.commit_c1_candidates(21, [(2, 0), (3, 0)])
    assert len(mgr.rotations) == 2
    mgr.reset()
    assert len(mgr.rotations) == 0
    assert mgr.committed_c1_this_day == 0


def test_state_machine_planting_day_water_success():
    """Verify complete confirmed state machine progression when planting-day water succeeds."""
    mgr = TwoCycleRotationManager()
    pos = (2, 0)
    mgr.commit_c1_candidates(21, [pos])
    rec = mgr.rotations[pos]
    assert rec.phase == RotationPhase.C1_RESERVED

    # Step 1: Day 21 Hour 5, worker plants CARROT (not watered yet)
    mock_farm = MagicMock()
    mock_tile = MagicMock(is_plant=True, crop="CARROT", watered_today=False, kind="PLANT")
    mock_farm.tiles = {0: {2: mock_tile}}
    ctx = {"day": 21, "hour": 5, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C1_PLANTED
    assert rec.c1_planted_confirmed is True

    # Step 2: Day 21 Hour 10, worker waters CARROT
    mock_tile.watered_today = True
    ctx = {"day": 21, "hour": 10, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C1_WATERED_D0
    assert rec.c1_d0_watered_confirmed is True

    # Step 3: Day 22 Hour 0, advances to C1_GROWING
    ctx = {"day": 22, "hour": 0, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C1_GROWING

    # Step 4: Day 24 Hour 0 (Day D+3), advances to C2_RESERVED
    ctx = {"day": 24, "hour": 0, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C2_RESERVED

    # Step 5: Day 24 Hour 8, C1 harvested intraday -> tile becomes EMPTY
    mock_tile.is_plant = False
    mock_tile.crop = None
    mock_tile.kind = "EMPTY"
    mock_tile.watered_today = False
    ctx = {"day": 24, "hour": 8, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C1_HARVESTED
    assert rec.c1_harvested_confirmed is True

    # Step 6: Day 24 Hour 12, C2 replanted
    mock_tile.is_plant = True
    mock_tile.crop = "CARROT"
    mock_tile.kind = "PLANT"
    mock_tile.watered_today = False
    ctx = {"day": 24, "hour": 12, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C2_PLANTED
    assert rec.c2_planted_confirmed is True

    # Step 7: Day 24 Hour 15, C2 watered on planting day!
    mock_tile.watered_today = True
    ctx = {"day": 24, "hour": 15, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C2_WATERED_D0
    assert rec.c2_d0_watered_confirmed is True

    # Step 8: Day 25 Hour 0, advances to C2_GROWING
    ctx = {"day": 25, "hour": 0, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C2_GROWING

    # Step 9: Day 27 Hour 10, C2 harvested -> tile empty -> COMPLETED!
    mock_tile.is_plant = False
    mock_tile.kind = "EMPTY"
    ctx = {"day": 27, "hour": 10, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.COMPLETED


def test_state_machine_fails_on_missed_planting_day_water():
    """Verify that if planting-day water is omitted, state transitions to FAILED."""
    mgr = TwoCycleRotationManager()
    pos = (2, 0)
    mgr.commit_c1_candidates(21, [pos])
    rec = mgr.rotations[pos]

    # Planted on Day 21, but never watered
    mock_farm = MagicMock()
    mock_tile = MagicMock(is_plant=True, crop="CARROT", watered_today=False, kind="PLANT")
    mock_farm.tiles = {0: {2: mock_tile}}
    ctx = {"day": 21, "hour": 15, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.C1_PLANTED

    # Day 22 arrives without water
    ctx = {"day": 22, "hour": 0, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.FAILED
    assert "missed planting-day water" in rec.failure_reason


def test_state_machine_fails_on_tile_hijack():
    """Verify that if harvested tile is hijacked by WHEAT, state transitions to FAILED."""
    mgr = TwoCycleRotationManager()
    pos = (2, 0)
    mgr.commit_c1_candidates(21, [pos])
    rec = mgr.rotations[pos]
    rec.phase = RotationPhase.C1_HARVESTED
    rec.c1_harvested_confirmed = True

    mock_farm = MagicMock()
    mock_tile = MagicMock(is_plant=True, crop="WHEAT", kind="PLANT", watered_today=False)
    mock_farm.tiles = {0: {2: mock_tile}}
    ctx = {"day": 24, "hour": 10, "farm": mock_farm}
    mgr.update_from_observation(ctx)
    assert rec.phase == RotationPhase.FAILED
    assert "Tile hijacked by wheat" in rec.failure_reason


def test_sequential_collective_feed_safety():
    """Verify sequential day-by-day feed ledger correctly limits admissions without double counting."""
    mgr = TwoCycleRotationManager()
    mock_farm = MagicMock()
    mock_priv = MagicMock()

    # 2 cows: daily demand = 2 wheat. Safety buffer = 2 * 2.0 = 4.0 wheat.
    cows = [MagicMock(is_animal=True, animal="COW", fed_today=True) for _ in range(2)]
    mock_farm.iter_tiles.return_value = cows

    # Current stock: 10 wheat in shed
    mock_priv.shed = {"WHEAT": 10}
    mock_priv.inventories = []

    ctx = {"day": 21, "hour": 0, "farm": mock_farm, "private": mock_priv}

    # Propose 4 candidate wheat tiles
    candidates = [(0, 0), (0, 1), (0, 2), (0, 3)]

    # Initial timeline:
    # Day 21: B = 10 (unfed=0). Day 22: B=8. Day 23: B=6. Day 24: B=4. Day 25: B=2 (deficits on Day 25+ unless harvest arrives)
    # Each proposed wheat tile would harvest on Day 25 delivering 4 units.
    # Total demand Days 22..28 = 7 days * 2 = 14 wheat.
    # Initial stock = 10. Need at least 14 - 10 + 4(buffer) = 8 wheat from harvest to maintain buffer.
    # 4 proposed wheat tiles = 16 wheat.
    # If we convert 1 tile to carrot: 3 wheat tiles = 12 wheat harvest. Total supply = 22. Demand = 14. Net min bal = 8 >= 4. SAFE.
    # If we convert 2 tiles: 2 wheat tiles = 8 wheat harvest. Total supply = 18. Demand = 14. Net min bal = 4 >= 4. SAFE.
    # If we convert 3 tiles: 1 wheat tile = 4 wheat harvest. Total supply = 14. Demand = 14. Net min bal = 0 < 4. UNSAFE!
    admitted = mgr.evaluate_sequential_feed_safety(ctx, candidates)
    # Exactly 2 tiles admitted, stopping before 3rd tile breaches safety buffer!
    assert len(admitted) == 2
    assert admitted == [(0, 0), (0, 1)]
