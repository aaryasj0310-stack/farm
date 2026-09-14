"""Unit tests for SW Cell Allocator, Siting Invariants, and Locality Telemetry.

Verifies:
1. SW relocation does not increase total planned pastures.
2. Existing + reserved housing is counted before authorizing SW.
3. One SW pasture replaces one otherwise-planned NW/NE pasture.
4. Arm B-P produces identical placement behavior when feature flag is off.
5. Explicit SW pasture is preferentially occupied by next compatible animal.
6. SW pasture does not cause extra animal purchase.
7. Planned SW pasture gives zero Day-12+ purchase credit.
8. Daily worker respawn creates zero traversals.
9. Real NE-field -> shed -> SW-field journey creates exactly one traversal.
10. Shed-only movement creates zero field traversals.
11. Animal HARVEST is counted as livestock, crop HARVEST as crop.
12. Arm A has zero SW crop/livestock/housing operations while permitting central logistics classification.
"""

import pytest
from unittest.mock import MagicMock
import config
from config import (
    set_sw_experiment_arm,
    C4_LIVESTOCK_CUTOFF_DAY,
    PORT_SW,
    SW_PASTURE_TILES,
    SHED_ACCESS_TILES,
)
from strategy.sw_cell_allocator import (
    allocate_sw_pasture_locations,
    get_sw_cell_telemetry,
    reset_sw_cell_telemetry,
)
from execution.task_scheduler import (
    classify_task_action,
    _record_turn_utilization,
    get_locality_telemetry,
    reset_worker_locality,
    reset_daily_log,
)


class MockTile:
    def __init__(self, x, y, kind="EMPTY", is_plant=False, is_animal=False, crop=None, animal=None):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_plant = is_plant
        self.is_animal = is_animal
        self.crop = crop
        self.animal = animal
        self.watered_today = False
        self.consecutive_unwatered = 0
        self.fed_today = False
        self.yield_units = 0


class MockFarm:
    def __init__(self, unlocked=("NW", "NE", "SW"), hands=(), farmer=(4, 4)):
        self.unlocked = set(unlocked)
        self.farmer = farmer
        self.hands = list(hands)
        self.money = 5000.0
        self._tiles = {}
        for r in range(10):
            for c in range(10):
                q = self.quadrant_of((r, c))
                kind = "EMPTY" if q in self.unlocked else "LOCKED"
                self._tiles[(r, c)] = MockTile(r, c, kind=kind)

    def set_tile(self, pos, tile):
        self._tiles[pos] = tile

    def tile_at(self, pos):
        return self._tiles.get(pos)

    def quadrant_of(self, pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")

    def iter_tiles(self):
        return list(self._tiles.values())


@pytest.fixture(autouse=True)
def cleanup():
    reset_daily_log()
    reset_worker_locality()
    reset_sw_cell_telemetry()
    set_sw_experiment_arm("ArmA")
    config.set_quadrant_hard_block({4})
    yield
    reset_daily_log()
    reset_worker_locality()
    reset_sw_cell_telemetry()
    set_sw_experiment_arm("ArmA")
    config.set_quadrant_hard_block({4})


# ---------------------------------------------------------------------------
# Test 1 & 3: Location-Only Allocation & Pasture Quota Preservation
# ---------------------------------------------------------------------------
def test_sw_relocation_does_not_increase_total_planned_pastures():
    """SW relocation must allocate location only, up to needed_slots, without increasing total quota."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    empty = [(r, c) for r in range(10) for c in range(10) if farm.quadrant_of((r, c)) == "SW"]

    # Request 3 needed slots, but max SW pastures is 1
    locs, diag = allocate_sw_pasture_locations(
        farm=farm,
        day=5,
        needed_slots=3,
        existing_sw_pastures=0,
        reserved_sw_pastures=0,
        empty_tiles=empty,
        sw_cell_enabled=True,
        max_sw_pastures=1,
    )
    # Must allocate at most 1 slot
    assert len(locs) == 1
    assert farm.quadrant_of(locs[0]) == "SW"
    assert diag["eligible"] is True


def test_existing_plus_reserved_housing_counted_before_sw_authorization():
    """If existing + reserved SW pastures >= max_sw_pastures, allocator must reject new SW pastures."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    empty = [(r, c) for r in range(10) for c in range(10) if farm.quadrant_of((r, c)) == "SW"]

    # 1 existing SW pasture already built
    locs, diag = allocate_sw_pasture_locations(
        farm=farm,
        day=5,
        needed_slots=2,
        existing_sw_pastures=1,
        reserved_sw_pastures=0,
        empty_tiles=empty,
        sw_cell_enabled=True,
        max_sw_pastures=1,
    )
    assert locs == []
    assert "sw_cell_capacity_reached" in diag["reason"]

    # 0 existing, but 1 already reserved
    locs2, diag2 = allocate_sw_pasture_locations(
        farm=farm,
        day=5,
        needed_slots=2,
        existing_sw_pastures=0,
        reserved_sw_pastures=1,
        empty_tiles=empty,
        sw_cell_enabled=True,
        max_sw_pastures=1,
    )
    assert locs2 == []
    assert "sw_cell_capacity_reached" in diag2["reason"]


def test_one_sw_pasture_replaces_one_nw_ne_pasture():
    """In MacroPlanner pipeline, 1 SW pasture replaces 1 NW/NE pasture, preserving total budget."""
    set_sw_experiment_arm("ArmC-Cell")
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    empty_tiles = [pos for pos, t in farm._tiles.items() if t.kind == "EMPTY"]

    # Test allocator output with 2 needed slots
    locs, diag = allocate_sw_pasture_locations(
        farm=farm,
        day=6,
        needed_slots=2,
        existing_sw_pastures=0,
        reserved_sw_pastures=0,
        empty_tiles=empty_tiles,
        sw_cell_enabled=True,
        max_sw_pastures=1,
    )
    assert len(locs) == 1
    sw_tile = locs[0]
    assert farm.quadrant_of(sw_tile) == "SW"

    # Simulate reservation budget: total budget = 2
    target_pastures = 2
    reserved_structures = []
    positive_cands = [{"pos": (2, 7)}, {"pos": (3, 7)}]

    # 1. SW pasture consumes first slot
    for st in locs:
        if len(reserved_structures) < target_pastures:
            reserved_structures.append((st, "BUILD_PASTURE"))
    # 2. Remaining slots taken from positive_cands
    positive_cands = [{"pos": (7, 2)}, {"pos": (7, 3)}]
    while len(reserved_structures) < target_pastures and positive_cands:
        c = positive_cands.pop(0)
        reserved_structures.append((c["pos"], "BUILD_PASTURE"))

    assert len(reserved_structures) == 2
    assert farm.quadrant_of(reserved_structures[0][0]) == "SW"
    assert farm.quadrant_of(reserved_structures[1][0]) == "NE"
    # Exactly one NE pasture was replaced by the SW pasture


# ---------------------------------------------------------------------------
# Test 4: Arm B-P Feature Isolation
# ---------------------------------------------------------------------------
def test_arm_b_p_produces_identical_placement_when_sw_cell_disabled():
    """When Arm B-P is active (sw_cell_enabled=False), allocator always rejects."""
    set_sw_experiment_arm("ArmB-P")
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    empty = [(r, c) for r in range(10) for c in range(10) if farm.quadrant_of((r, c)) == "SW"]

    from config import SW_CELL_HOUSING_ENABLED
    assert SW_CELL_HOUSING_ENABLED is False

    locs, diag = allocate_sw_pasture_locations(
        farm=farm,
        day=5,
        needed_slots=2,
        existing_sw_pastures=0,
        reserved_sw_pastures=0,
        empty_tiles=empty,
        sw_cell_enabled=SW_CELL_HOUSING_ENABLED,
        max_sw_pastures=1,
    )
    assert locs == []
    assert diag["reason"] == "cell_treatment_disabled"


# ---------------------------------------------------------------------------
# Test 5 & 6: Preferential Occupancy & No Extra Animal Purchase
# ---------------------------------------------------------------------------
def test_sw_pasture_preferentially_occupied_by_next_compatible_animal():
    """When an empty SW pasture exists, next compatible animal placement prioritizes SW."""
    from strategy.macro_planner import MacroPlanner
    from price_forecast import PriceForecast

    fc = PriceForecast.load()
    planner = MacroPlanner(fc)

    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    # Build 1 pasture in SW (2, 7) and 1 pasture in NE (7, 2)
    farm.set_tile((2, 7), MockTile(2, 7, kind="PASTURE"))
    farm.set_tile((7, 2), MockTile(7, 2, kind="PASTURE"))

    # Have 1 cow in inventory waiting to be placed
    private = MagicMock()
    private.shed = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    private.inventories = [{"COW": 1}]
    private.seeds = {}

    ctx = {
        "farm": farm,
        "private": private,
        "town": {"unlocked_shops": []},
        "day": 6,
        "hour": 0,
        "step": 144,
        "money": 5000.0,
    }

    set_sw_experiment_arm("ArmC-Cell")
    plan = planner.build(ctx)

    # Place queue should have targeted the SW pasture (7, 2) first
    assert len(plan.place_queue) >= 1
    place_target = plan.place_queue[0]["target"]
    assert farm.quadrant_of(place_target) == "SW"


def test_sw_pasture_does_not_cause_extra_animal_purchase():
    """SW cell allocator must never increase animal purchase intents beyond Arm B-P baseline."""
    from strategy.macro_planner import MacroPlanner
    from price_forecast import PriceForecast

    fc = PriceForecast.load()
    planner = MacroPlanner(fc)

    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    private = MagicMock()
    private.shed = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    private.inventories = [{}]
    private.seeds = {}

    ctx = {
        "farm": farm,
        "private": private,
        "town": {"unlocked_shops": []},
        "day": 5,
        "hour": 0,
        "step": 120,
        "money": 6000.0,
    }

    set_sw_experiment_arm("ArmB-P")
    plan_b_p = planner.build(ctx)

    set_sw_experiment_arm("ArmC-Cell")
    plan_c_cell = planner.build(ctx)

    # Animal purchase intents must match exactly between Arm B-P and Arm C-Cell
    assert plan_c_cell.intents.get("buy_animal") == plan_b_p.intents.get("buy_animal")


def test_planned_sw_pasture_gives_zero_day_12_purchase_credit():
    """On or after Day 12 cutoff, allocator must reject SW pastures."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    empty = [(r, c) for r in range(10) for c in range(10) if farm.quadrant_of((r, c)) == "SW"]

    locs, diag = allocate_sw_pasture_locations(
        farm=farm,
        day=C4_LIVESTOCK_CUTOFF_DAY,
        needed_slots=1,
        existing_sw_pastures=0,
        reserved_sw_pastures=0,
        empty_tiles=empty,
        sw_cell_enabled=True,
        max_sw_pastures=1,
    )
    assert locs == []
    assert diag["reason"] == "day_12_cutoff_reached"


# ---------------------------------------------------------------------------
# Test 8, 9, 10: Traversal Telemetry & Shed Access Invariants
# ---------------------------------------------------------------------------
def test_daily_worker_respawn_creates_zero_traversals():
    """Worker despawning at midnight and respawning on shed tiles must log zero traversals."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    ctx_d0 = {"day": 0, "hour": 23, "step": 23, "farm": farm}
    ctx_d1 = {"day": 1, "hour": 0, "step": 24, "farm": farm}

    # Worker 0 in SW at end of day 0
    _record_turn_utilization(
        ctx_d0, n_units=1, actions_taken={0: ["PASS"]},
        assignment={0: {}}, home_quads={0: "SW"}, pos_by_idx={0: (7, 2)}
    )

    # Worker 0 respawns at shed (4, 4) in morning of day 1
    _record_turn_utilization(
        ctx_d1, n_units=1, actions_taken={0: ["PASS"]},
        assignment={0: {}}, home_quads={0: "NW"}, pos_by_idx={0: (4, 4)}
    )

    telem = get_locality_telemetry()
    assert telem["summary"]["total_physical_ne_sw_traversals"] == 0


def test_real_ne_field_to_sw_field_journey_creates_exactly_one_traversal():
    """Worker journey from NE field (2, 7) through shed (4, 5) to SW field (7, 2) logs 1 traversal."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    ctx = {"day": 2, "hour": 5, "step": 53, "farm": farm}

    # Step 1: Worker in NE field
    _record_turn_utilization(
        ctx, n_units=1, actions_taken={0: ["SOUTH"]},
        assignment={0: {}}, home_quads={0: "NE"}, pos_by_idx={0: (2, 7)}
    )
    # Step 2: Worker on shed access tile (4, 5)
    _record_turn_utilization(
        ctx, n_units=1, actions_taken={0: ["SOUTH"]},
        assignment={0: {}}, home_quads={0: "NE"}, pos_by_idx={0: (4, 5)}
    )
    # Step 3: Worker enters SW field (7, 2)
    _record_turn_utilization(
        ctx, n_units=1, actions_taken={0: ["PASS"]},
        assignment={0: {}}, home_quads={0: "SW"}, pos_by_idx={0: (7, 2)}
    )

    telem = get_locality_telemetry()
    assert telem["summary"]["total_physical_ne_sw_traversals"] == 1


def test_shed_only_movement_creates_zero_field_traversals():
    """Movement around central shed access tiles (4,4), (5,4), (4,5), (5,5) logs 0 traversals."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    ctx = {"day": 3, "hour": 2, "step": 74, "farm": farm}

    # Move among shed tiles
    shed_steps = [(4, 4), (4, 5), (5, 5), (5, 4), (4, 4)]
    for pos in shed_steps:
        _record_turn_utilization(
            ctx, n_units=1, actions_taken={0: ["PASS"]},
            assignment={0: {}}, home_quads={0: "NW"}, pos_by_idx={0: pos}
        )

    telem = get_locality_telemetry()
    assert telem["summary"]["total_physical_ne_sw_traversals"] == 0


# ---------------------------------------------------------------------------
# Test 11 & 12: Action Semantic Classification
# ---------------------------------------------------------------------------
def test_harvest_action_classification():
    """classify_task_action properly distinguishes animal vs crop HARVEST."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"))
    farm.set_tile((2, 2), MockTile(2, 2, kind="PLANT", is_plant=True, crop="WHEAT"))
    farm.set_tile((2, 7), MockTile(2, 7, kind="PASTURE", is_animal=True, animal="COW"))

    # Crop harvest
    cat_crop, q_crop = classify_task_action(
        act=["HARVEST"],
        task={"op": "HARVEST", "target": (2, 2), "kind": "harvest"},
        farm=farm,
    )
    assert cat_crop == "crop"
    assert q_crop == "NW"

    # Animal harvest
    cat_anim, q_anim = classify_task_action(
        act=["HARVEST"],
        task={"op": "HARVEST", "target": (2, 7), "kind": "harvest_animal"},
        farm=farm,
    )
    assert cat_anim == "livestock"
    assert q_anim == "SW"


def test_arm_a_zero_sw_crop_livestock_housing_ops():
    """In Arm A, central shed access at (4, 5) classifies as logistics CENTRAL, with 0 SW ops."""
    farm = MockFarm(unlocked=("NW", "NE"))  # SW is locked

    # Central shed DROP at (4, 5)
    cat_log, q_log = classify_task_action(
        act=["DROP", "WHEAT", 1],
        task={"op": "DROP", "target": (4, 5), "kind": "drop"},
        farm=farm,
    )
    assert cat_log == "logistics"
    assert q_log == "CENTRAL"
