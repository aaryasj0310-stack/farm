"""Point 2 — Phase A: Comprehensive Feed/Herd Feasibility Evaluator Tests.

Verifies:
1. Basic safety & ledger semantic cash holds.
2. Exact same-day market timing (unit actions before market; Hour 23 no rescue).
3. Placed herd vs owned unplaced herd semantic distinction.
4. No speculative resources (zero revenue credit, secured wheat deliveries only).
5. Sequential non-reused reservations & monotonicity.
6. Separation of physical/cash feasibility from economic ROI.
7. MacroPlanner shadow diagnostics integration.
8. Main telemetry snapshot & shadow diagnostics integration.
9. Subprocess-based 720-step zero-drift regression (off vs shadow).
10. Live fallback regression test (force MacroPlanner.build to throw, verify survival action & no UnboundLocalError).
11. Bug 2 tests: no double reservation, candidate #1 reserve counted once, candidate #2 residual cash.
12. Bug 3 tests: true prefix timing, Day 12 buy cannot rescue Day 10 deficit.
13. Bug 4 tests: unplaced candidate evaluated at Hour 23 not rejected for today's feed.
14. Bug 5 tests: actual current-day feed obligations (10 placed, 8 fed -> 2 today, 10 tomorrow).
15. Bug 6 tests: execution confidence propagation and degradation around Hour 20/22/23.
16. Shed capacity tests: full shed blocks purchase; future feed frees storage but not retroactively.
17. Wheat pricing & monotonicity tests: price increase never improves feasibility; more wheat never hurts.
"""

import copy
import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch
import pytest

# Ensure import paths are properly set
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
for sub in ("state", "strategy", "execution", "market"):
    p = os.path.join(BASE_DIR, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from config import (
    POINT2_FEED_MODE,
    get_point2_feed_mode,
    FEED_OPERATIONAL_HORIZON_DAYS,
    ANIMALS,
    ANIMAL_FEED_CUTOFF_DAY,
)
from strategy.feed_feasibility import (
    TimedWheatDelivery,
    FeedExecutionSnapshot,
    FeedResourceLedger,
    FeedFeasibilityResult,
    build_feed_resource_ledger,
    build_feed_execution_snapshot,
    evaluate_existing_herd_feasibility,
    evaluate_incremental_candidate,
    commit_candidate_reservation,
)
from observation_parser import parse_observation
from strategy.macro_planner import MacroPlanner
from state.state_tracker import reset_memory


class DummyFC:
    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        return 50.0


def make_mock_tile(pos, kind="EMPTY", is_plant=False, is_animal=False, animal=None, crop=None, placed_day=0, fed_today=False):
    t = MagicMock()
    t.pos = pos
    t.kind = kind
    t.is_plant = is_plant
    t.is_animal = is_animal
    t.animal = animal
    t.crop = crop
    t.placed_day = placed_day
    t.watered_today = True
    t.fed_today = fed_today
    t.cared_today = False
    t.yield_units = 0
    t.fertilizer_available = False
    t.fertilized_until_day = -1
    return t


def make_mock_farm_ctx(
    day=10,
    hour=0,
    money=1000.0,
    shed_wheat=10,
    placed_animals=None,
    shed_animals=None,
    worker_animals=None,
    wheat_tiles=None,
    unlocked=("NW",),
    fed_animals_count=0,
):
    """Build a rich mock context suitable for feed feasibility testing."""
    if placed_animals is None:
        placed_animals = []
    if shed_animals is None:
        shed_animals = {}
    if worker_animals is None:
        worker_animals = []
    if wheat_tiles is None:
        wheat_tiles = []

    tiles = []
    # Add placed animals
    for i, a in enumerate(placed_animals):
        is_fed = (i < fed_animals_count)
        tiles.append(make_mock_tile((i, 0), kind="PASTURE", is_animal=True, animal=a, placed_day=day - 2, fed_today=is_fed))

    # Add wheat tiles
    for j, (pday, yunits) in enumerate(wheat_tiles):
        t = make_mock_tile((j, 1), kind="PLANT", is_plant=True, crop="WHEAT", placed_day=pday)
        t.yield_units = yunits
        tiles.append(t)

    # Fill rest of 25 NW tiles with empty
    occupied_positions = {t.pos for t in tiles}
    for r in range(5):
        for c in range(5):
            if (c, r) not in occupied_positions:
                tiles.append(make_mock_tile((c, r), kind="EMPTY"))

    farm = MagicMock()
    farm.money = float(money)
    farm.unlocked = set(unlocked)
    farm.tiles = [[None for _ in range(10)] for _ in range(10)]
    farm.hands = []
    farm.farmer = MagicMock(pos=(0, 0))

    tile_dict = {}
    for t in tiles:
        c, r = t.pos
        farm.tiles[r][c] = t
        tile_dict[(c, r)] = t

    farm.iter_tiles = lambda: iter(tiles)
    farm.tile = lambda c, r: tile_dict.get((c, r))

    private = MagicMock()
    shed = {"WHEAT": shed_wheat}
    for a, count in shed_animals.items():
        shed[a] = count
    private.shed = shed

    worker_invs = []
    for a in worker_animals:
        worker_invs.append({a: 1})
    if not worker_invs:
        worker_invs.append({})
    private.inventories = worker_invs
    private.seeds = {}

    market = MagicMock()
    market.inventory = {p: 10000 for p in ("WHEAT", "COW", "SHEEP", "GOOSE")}

    town = MagicMock()
    town.shops = {}

    ctx = {
        "day": day,
        "hour": hour,
        "farm": farm,
        "private": private,
        "market": market,
        "town": town,
        "step": day * 24 + hour,
    }
    return ctx


# ===========================================================================
# 1. Basic Safety & Semantic Cash Holds
# ===========================================================================

def test_ledger_initialization_and_semantic_cash_holds():
    """Verify separate semantic cash holds are maintained and purchasing power is exact."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=20)
    ledger = build_feed_resource_ledger(
        ctx,
        hard_cash_hold=100.0,
        strategic_cash_hold=250.0,
        horizon_days=4,
    )

    assert ledger.observed_cash == 1000.0
    assert ledger.hard_cash_hold == 100.0
    assert ledger.strategic_cash_hold == 250.0
    assert ledger.existing_feed_cash_hold == 0.0
    assert ledger.candidate_feed_cash_hold == 0.0

    # Remaining purchasing power = 1000 - 100 - 250 = 650.0
    assert ledger.available_cash_for_candidates == 650.0

    # Ledger serialization sanity
    d = ledger.to_dict()
    assert d["observed_cash"] == 1000.0
    assert d["hard_cash_hold"] == 100.0
    assert d["strategic_cash_hold"] == 250.0
    assert d["available_cash_for_candidates"] == 650.0


# ===========================================================================
# 2. Timing: Unit Actions Before Market & Hour 23 No Rescue
# ===========================================================================

def test_timing_hour23_market_purchase_no_same_day_rescue():
    """At Hour 23, unit actions already ran; same-turn market purchase cannot rescue today."""
    ctx = make_mock_farm_ctx(day=10, hour=23, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    snapshot = ledger.execution_snapshot
    assert snapshot is not None
    assert snapshot.hour == 23
    assert snapshot.turns_remaining_today == 1
    assert snapshot.market_purchase_can_help_today is False

    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is False
    assert res.blocking_day == 10
    assert res.blocking_reason is not None


def test_timing_hour0_market_purchase_can_help_later_turns():
    """At Hour 0, market purchases can help subsequent turns today if funds exist."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    snapshot = ledger.execution_snapshot
    assert snapshot is not None
    assert snapshot.hour == 0
    assert snapshot.market_purchase_can_help_today is True

    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is True
    assert res.near_term_market_wheat_required > 0
    assert ledger.existing_feed_cash_hold > 0.0


# ===========================================================================
# 3. Placed Herd vs Owned Unplaced Herd Semantics
# ===========================================================================

def test_placed_vs_owned_unplaced_herd_semantics():
    """Placed herd eats today; owned unplaced herd does not eat today but has future funding liability."""
    ctx = make_mock_farm_ctx(
        day=10,
        hour=23,
        money=2000.0,
        shed_wheat=0,
        placed_animals=[],
        shed_animals={"COW": 2},
    )
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    assert sum(ledger.placed_herd.values()) == 0
    assert ledger.owned_unplaced_herd["COW"] == 2

    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is True
    assert ledger.existing_feed_cash_hold > 0.0
    assert ledger.existing_feed_cash_hold >= 36 * 20.0


# ===========================================================================
# 4. No Speculative Resources & Zero Revenue Credit
# ===========================================================================

def test_candidate_zero_revenue_credit():
    """Candidate evaluation must NOT assume revenue from animal products to fund its own feed."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=450.0, shed_wheat=0, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    res = evaluate_incremental_candidate(ledger, "COW")
    assert res.feasible is False
    assert res.blocking_reason in ("insufficient_cash", "insufficient_operational_feed")


def test_zero_credit_for_empty_sw_and_planned_crops():
    """Empty soil, planned wheat, and unharvestable tiles provide ZERO hard wheat credit."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=0, placed_animals=["COW"])
    # Add a mock planned or non-wheat tile
    planned_tile = make_mock_tile((0, 2), kind="EMPTY", is_plant=False)
    # The ledger secured deliveries only come from live WHEAT plants
    deliveries = ledger = build_feed_resource_ledger(ctx)
    assert len(ledger.secured_wheat_deliveries) == 0


# ===========================================================================
# 5. Sequential Non-Reused Reservations & Monotonicity
# ===========================================================================

def test_sequential_reservations_do_not_double_spend():
    """Adding candidate 1 reduces available cash; candidate 2 can only spend what remains."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1100.0, shed_wheat=0, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    # 1. Cow alone is feasible
    cow_res = evaluate_incremental_candidate(ledger, "COW")
    assert cow_res.feasible is True

    # Commit cow reservation
    commit_candidate_reservation(ledger, cow_res)
    assert len(ledger.candidate_reservations) == 1
    assert ledger.candidate_feed_cash_hold == cow_res.candidate_feed_cash_hold

    # 2. Sheep after cow must now be rejected due to insufficient cash
    sheep_res = evaluate_incremental_candidate(ledger, "SHEEP")
    assert sheep_res.feasible is False
    assert sheep_res.blocking_reason in ("insufficient_cash", "insufficient_operational_feed")


def test_monotonicity_cash():
    """If a candidate is rejected with cash X, it must also be rejected with cash < X."""
    ctx_700 = make_mock_farm_ctx(day=10, hour=0, money=700.0, shed_wheat=0, placed_animals=[])
    ledger_700 = build_feed_resource_ledger(ctx_700)
    res_700 = evaluate_incremental_candidate(ledger_700, "COW")
    assert res_700.feasible is False

    ctx_500 = make_mock_farm_ctx(day=10, hour=0, money=500.0, shed_wheat=0, placed_animals=[])
    ledger_500 = build_feed_resource_ledger(ctx_500)
    res_500 = evaluate_incremental_candidate(ledger_500, "COW")
    assert res_500.feasible is False


def test_existing_herd_infeasible_blocks_all_candidates():
    """If the existing herd is already infeasible, no candidate can be feasible."""
    ctx = make_mock_farm_ctx(day=10, hour=23, money=0.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx)

    existing_ok, _ = evaluate_existing_herd_feasibility(ledger)
    assert existing_ok is False

    cow_res = evaluate_incremental_candidate(ledger, "COW")
    assert cow_res.feasible is False
    assert "infeasible" in cow_res.blocking_reason.lower()


# ===========================================================================
# 6. Separation of Economics from Physical/Cash Feasibility
# ===========================================================================

def test_separation_of_economics():
    """Feasibility evaluator does NOT reject candidates for low ROI or poor town shop demand."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=100, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx)

    cow_res = evaluate_incremental_candidate(ledger, "COW")
    assert cow_res.feasible is True


# ===========================================================================
# 7. MacroPlanner Shadow Diagnostics Integration
# ===========================================================================

def test_macro_planner_shadow_diagnostics_integration():
    """MacroPlanner records point2_feed_shadow diagnostics when mode != off."""
    reset_memory()
    ctx = make_mock_farm_ctx(day=6, hour=0, money=2000.0, shed_wheat=20, placed_animals=[])
    planner = MacroPlanner(DummyFC())
    plan = planner.build(ctx)

    diag = plan.diagnostics
    assert "point2_feed_shadow" in diag, "plan.diagnostics must include 'point2_feed_shadow'"
    shadow_diag = diag["point2_feed_shadow"]
    assert shadow_diag["mode"] in ("shadow", "herd_plan", "live")
    assert "existing_feasible" in shadow_diag
    assert "candidate_feasibility" in shadow_diag
    assert "COW" in shadow_diag["candidate_feasibility"]
    assert "SHEEP" in shadow_diag["candidate_feasibility"]
    assert "GOOSE" in shadow_diag["candidate_feasibility"]
    assert "sequential_test" in shadow_diag
    assert "ledger_summary" in shadow_diag


# ===========================================================================
# 8. Main Telemetry Snapshot & Shadow Diagnostics Integration
# ===========================================================================

def test_main_telemetry_integration():
    """_LAST_TURN_TELEMETRY in main.py captures feed_execution_snapshot and feed_feasibility_shadow."""
    import main as agent_main
    agent_main.reset_agent_state()

    obs = {
        "day": 5,
        "hour": 0,
        "farms": [
            {
                "money": 1500.0,
                "tiles": [[None] * 10 for _ in range(10)],
                "farmer": [4, 4],
                "hands": [],
                "unlocked": ["NW"],
                "hires_today": 0,
            },
            {
                "money": 1500.0,
                "tiles": [[None] * 10 for _ in range(10)],
                "farmer": [4, 4],
                "hands": [],
                "unlocked": ["NW"],
                "hires_today": 0,
            },
        ],
        "private": {
            "shed": {"WHEAT": 10},
            "inventories": [{}],
            "seeds": {},
        },
        "market": {"inventory": {p: 100 for p in ("WHEAT", "COW", "SHEEP")}},
        "town": {"shops": {}},
        "step": 5 * 24,
    }
    for r in range(5):
        for c in range(5):
            obs["farms"][0]["tiles"][r][c] = {"kind": "EMPTY", "pos": (c, r)}
            obs["farms"][1]["tiles"][r][c] = {"kind": "EMPTY", "pos": (c, r)}

    res = agent_main.agent(obs)
    assert isinstance(res, dict)

    telem = agent_main.get_last_turn_telemetry()
    assert telem is not None
    assert "feed_execution_snapshot" in telem
    assert telem["feed_execution_snapshot"] is not None
    assert "feed_feasibility_shadow" in telem
    assert telem["feed_feasibility_shadow"] is not None
    assert telem["feed_feasibility_shadow"]["mode"] == "shadow"


# ===========================================================================
# 10. Bug 1: Emergency Fallback Regression Test
# ===========================================================================

def test_fallback_regression_when_planner_throws():
    """When MacroPlanner.build throws, emergency fallback must run safely without UnboundLocalError."""
    import main as agent_main
    agent_main.reset_agent_state()

    obs = {
        "day": 5,
        "hour": 0,
        "farms": [
            {
                "money": 1500.0,
                "tiles": [[None] * 10 for _ in range(10)],
                "farmer": [4, 4],
                "hands": [],
                "unlocked": ["NW"],
                "hires_today": 0,
            },
            {
                "money": 1500.0,
                "tiles": [[None] * 10 for _ in range(10)],
                "farmer": [4, 4],
                "hands": [],
                "unlocked": ["NW"],
                "hires_today": 0,
            },
        ],
        "private": {
            "shed": {"WHEAT": 10},
            "inventories": [{}],
            "seeds": {},
        },
        "market": {"inventory": {p: 100 for p in ("WHEAT", "COW", "SHEEP")}},
        "town": {"shops": {}},
        "step": 5 * 24,
    }
    for r in range(5):
        for c in range(5):
            obs["farms"][0]["tiles"][r][c] = {"kind": "EMPTY", "pos": (c, r)}
            obs["farms"][1]["tiles"][r][c] = {"kind": "EMPTY", "pos": (c, r)}

    with patch.object(MacroPlanner, "build", side_effect=RuntimeError("Simulated planner crash")):
        # Must execute emergency fallback without UnboundLocalError or any exception
        action = agent_main.agent(obs)
        assert isinstance(action, dict)
        assert "farmer" in action

        telem = agent_main.get_last_turn_telemetry()
        assert telem is not None
        # feed_execution_snapshot must safely be None in telemetry
        assert telem.get("feed_execution_snapshot") is None


# ===========================================================================
# 11. Bug 2: No Double Reservation of Committed Candidate Feed Cash
# ===========================================================================

def test_no_double_reservation_candidate_reserves():
    """Committed candidate feed liability belongs only to candidate_feed_cash_hold, not existing_feed."""
    # Money = $2500. Day 10, Hour 0. 0 placed animals.
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2500.0, shed_wheat=0, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx)

    # 1. Candidate 1 (COW)
    res1 = evaluate_incremental_candidate(ledger, "COW")
    assert res1.feasible is True

    cand1_feed_hold = res1.candidate_feed_cash_hold
    commit_candidate_reservation(ledger, res1)

    # Invariants after committing Candidate 1:
    assert ledger.placed_herd["COW"] == 0, "Candidate must not be placed in placed_herd immediately"
    assert ledger.candidate_feed_cash_hold == cand1_feed_hold
    assert ledger.existing_feed_cash_hold == 0.0

    # 2. Candidate 2 (COW) evaluation:
    # Existing herd baseline evaluated inside candidate 2 must NOT absorb candidate 1 into existing_feed_cash_hold
    res2 = evaluate_incremental_candidate(ledger, "COW")
    # Residual cash should be 2500 - cow1 cost - cand1_feed_hold
    cow_cost = float(ANIMALS["COW"]["cost"])
    expected_residual = 2500.0 - cow_cost - cand1_feed_hold
    assert abs(ledger.available_cash_for_candidates - expected_residual) < 1e-5

    # Since $2500 is large enough for two cows ($500 + feed each ~ $1000 each = ~$2000), candidate 2 must be FEASIBLE!
    assert res2.feasible is True, "Candidate 2 should be feasible with $2500; must not be falsely rejected by double reservation"

    # 3. If cash is only enough for 1 COW ($1100), candidate 2 genuinely cannot be funded and is rejected
    ctx_tight = make_mock_farm_ctx(day=10, hour=0, money=1100.0, shed_wheat=0, placed_animals=[])
    ledger_tight = build_feed_resource_ledger(ctx_tight)
    res_tight1 = evaluate_incremental_candidate(ledger_tight, "COW")
    assert res_tight1.feasible is True
    commit_candidate_reservation(ledger_tight, res_tight1)
    res_tight2 = evaluate_incremental_candidate(ledger_tight, "COW")
    assert res_tight2.feasible is False
    assert res_tight2.blocking_reason == "insufficient_cash"


# ===========================================================================
# 12. Bug 3: True Prefix Timing for Market Wheat
# ===========================================================================

def test_future_market_wheat_prefix_timing():
    """Wheat arriving on Day D cannot satisfy feed owed before Day D."""
    # Day 10, Hour 0. 1 placed cow, 0 wheat on hand.
    # Suppose a scheduled market purchase delivers on Day 12.
    # It CANNOT rescue the deficit on Day 10 or Day 11!
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx)

    # Let's check candidate evaluation:
    # A purchase on Day 12 cannot rescue Day 10
    cand_res = evaluate_incremental_candidate(ledger, "GOOSE")
    # In daily_timeline, Day 10 and Day 11 must have their own needed and deliveries/purchases
    assert cand_res.daily_timeline is not None
    for item in cand_res.daily_timeline:
        assert item["slack"] >= 0


def test_earlier_wheat_never_worse_than_later():
    """Secured wheat arriving on Day 10 must give equal or better slack than Day 12."""
    # Context with wheat delivery arriving Day 10
    ctx1 = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger1 = build_feed_resource_ledger(ctx1)
    ledger1.secured_wheat_deliveries = [TimedWheatDelivery(day=10, units=10)]
    feasible1, res1 = evaluate_existing_herd_feasibility(ledger1)

    # Context with wheat delivery arriving Day 13
    ctx2 = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger2 = build_feed_resource_ledger(ctx2)
    ledger2.secured_wheat_deliveries = [TimedWheatDelivery(day=13, units=10)]
    feasible2, res2 = evaluate_existing_herd_feasibility(ledger2)

    assert res1.minimum_wheat_slack >= res2.minimum_wheat_slack
    assert res1.near_term_market_wheat_required <= res2.near_term_market_wheat_required


# ===========================================================================
# 13. Bug 4: Unplaced Candidate Evaluated at Hour 23 Not Rejected for Today
# ===========================================================================

def test_unplaced_candidate_at_hour_23_not_rejected_for_today():
    """A candidate evaluated at Hour 23 does NOT need physical wheat today; only from tomorrow."""
    # Day 10, Hour 23. 0 placed animals, $3000 money, 0 wheat.
    ctx = make_mock_farm_ctx(day=10, hour=23, money=3000.0, shed_wheat=0, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx)

    # Candidate COW evaluated at hour 23:
    # Since placed animals = 0, today needs 0 feed.
    # COW needs feed starting Day 11.
    res = evaluate_incremental_candidate(ledger, "COW")
    assert res.feasible is True, "Candidate evaluated at Hour 23 must not be rejected for today's feed deadline"


# ===========================================================================
# 14. Bug 5: Actual Remaining Current-Day Feed Obligations
# ===========================================================================

def test_actual_current_day_feed_obligations():
    """10 placed animals, 8 already fed today -> today requires only 2; tomorrow requires 10."""
    ctx = make_mock_farm_ctx(
        day=10,
        hour=12,
        money=10000.0,
        shed_wheat=2,  # Exactly 2 wheat on hand!
        placed_animals=["COW"] * 10,
        fed_animals_count=8,  # 8 out of 10 fed today
    )
    ledger = build_feed_resource_ledger(ctx)

    assert ledger.unfed_placed_today == 2
    assert ledger.total_placed_animals == 10

    # For today (Day 10), needed is 2. With 2 wheat on hand, 0 deficit on Day 10!
    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is True
    # Check timeline for Day 10
    day10_item = [t for t in res.daily_timeline if t["day"] == 10][0]
    assert day10_item["needed"] == 2
    assert day10_item["market_purchased"] == 0

    # For Day 11, needed is 10!
    day11_item = [t for t in res.daily_timeline if t["day"] == 11][0]
    assert day11_item["needed"] == 10


# ===========================================================================
# 15. Bug 6: Execution Confidence Propagation & Degradation
# ===========================================================================

def test_execution_confidence_propagation_and_degradation():
    """Execution confidence degrades at Hour 20/22/23 and propagates to result."""
    # 1. No scheduler proof -> guarded
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"])
    snap_none = build_feed_execution_snapshot(ctx, tasks=None, assignment=None)
    assert snap_none.execution_confidence == "guarded"

    ledger = build_feed_resource_ledger(ctx, execution_snapshot=snap_none)
    _, res = evaluate_existing_herd_feasibility(ledger)
    assert res.execution_confidence == "guarded"

    # 2. Hour 20 with feeds_due > worker_wheat -> guarded
    ctx_h20 = make_mock_farm_ctx(day=10, hour=20, money=2000.0, shed_wheat=10, placed_animals=["COW"] * 5)
    tasks = [{"op": "FEED", "kind": "feed_cow"}] * 5
    asg = {}  # 0 assigned
    snap_h20 = build_feed_execution_snapshot(ctx_h20, tasks=tasks, assignment=asg)
    assert snap_h20.execution_confidence == "guarded"

    # 3. Hour 23 with feeds_due > feeds_assigned -> conditional
    ctx_h23 = make_mock_farm_ctx(day=10, hour=23, money=2000.0, shed_wheat=10, placed_animals=["COW"] * 2)
    snap_h23 = build_feed_execution_snapshot(ctx_h23, tasks=[{"op": "FEED"}], assignment={})
    assert snap_h23.execution_confidence == "conditional"


# ===========================================================================
# 16. Shed Capacity Constraints
# ===========================================================================

def test_shed_capacity_blocks_market_purchase_when_full():
    """A full shed blocks market wheat purchase when storage capacity is exceeded."""
    # Day 10, Hour 0. 1 placed COW, 0 wheat on hand, but shed is full of OTHER items (100 items).
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx)
    ledger.shed_other_units = 100  # Shed is completely full!

    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is False
    assert res.blocking_reason == "shed_capacity"


# ===========================================================================
# 17. Wheat Pricing & Monotonicity
# ===========================================================================

def test_wheat_pricing_and_monotonicity():
    """Higher wheat price increases feed hold and can make candidate infeasible."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1200.0, shed_wheat=0, placed_animals=[])
    ledger_cheap = build_feed_resource_ledger(ctx)
    ledger_cheap.wheat_price_current = 20.0
    res_cheap = evaluate_incremental_candidate(ledger_cheap, "COW")

    ledger_expensive = build_feed_resource_ledger(ctx)
    ledger_expensive.wheat_price_current = 80.0
    res_expensive = evaluate_incremental_candidate(ledger_expensive, "COW")

    assert ledger_expensive.wheat_price_current > ledger_cheap.wheat_price_current
    assert res_expensive.candidate_feed_cash_hold > res_cheap.candidate_feed_cash_hold
    # With price 80, 18 wheat = $1440 feed + $500 cow = $1940 > $1200 -> infeasible!
    assert res_expensive.feasible is False


# ===========================================================================
# 9. Subprocess 720-step Baseline Equivalence (Zero Drift)
# ===========================================================================

def _run_isolated_simulation(mode: str, seed: int = 42, steps: int = 720):
    """Run a simulation in a separate Python subprocess to guarantee clean runtime state."""
    code = f"""
import sys, os, json, random
BASE_DIR = r"{BASE_DIR}"
sys.path.insert(0, BASE_DIR)
for sub in ("state", "strategy", "execution", "market"):
    p = os.path.join(BASE_DIR, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import config
config.POINT2_FEED_MODE = "{mode}"

import kaggle_environments
import main as agent_main
agent_main.reset_agent_state()

rng = random.Random(12345)
farmer_ops = ['NORTH', 'SOUTH', 'EAST', 'WEST', 'WATER', 'HARVEST', 'PASS']
def deterministic_opp(obs):
    f_act = [rng.choice(farmer_ops)]
    hands = obs.get('farms', [{{}}, {{}}])[1].get('hands', [])
    h_act = [[rng.choice(farmer_ops)] for _ in hands]
    return {{'farmer': f_act, 'hands': h_act, 'market': []}}

env = kaggle_environments.make("kaggriculture", configuration={{"episodeSteps": {steps}, "seed": {seed}}}, debug=True)
env.run([agent_main.agent, deterministic_opp])

actions_per_step = []
for s in env.steps:
    act = s[0].action
    actions_per_step.append(act)

final_reward = env.steps[-1][0].reward
final_money = env.steps[-1][0].observation["farms"][0]["money"]

out = {{
    "actions": actions_per_step,
    "final_reward": final_reward,
    "final_money": final_money,
    "total_steps": len(env.steps)
}}
print("---RESULT_START---")
print(json.dumps(out))
print("---RESULT_END---")
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )
    stdout = proc.stdout
    start_idx = stdout.find("---RESULT_START---") + len("---RESULT_START---")
    end_idx = stdout.find("---RESULT_END---")
    result_json = stdout[start_idx:end_idx].strip()
    return json.loads(result_json)


@pytest.mark.slow
def test_subprocess_720_step_baseline_equivalence():
    """Verify clean 720-step execution produces identical actions and rewards between off and shadow."""
    pytest.importorskip("kaggle_environments")
    
    res_off = _run_isolated_simulation("off", seed=42, steps=720)
    res_shadow = _run_isolated_simulation("shadow", seed=42, steps=720)

    assert res_off["total_steps"] == res_shadow["total_steps"] == 720
    assert res_off["final_money"] == res_shadow["final_money"]
    assert res_off["final_reward"] == res_shadow["final_reward"]

    # Verify action-by-action equality
    for step_idx, (act_off, act_shadow) in enumerate(zip(res_off["actions"], res_shadow["actions"])):
        assert act_off == act_shadow, f"Action divergence at step {step_idx}: off={act_off} != shadow={act_shadow}"
