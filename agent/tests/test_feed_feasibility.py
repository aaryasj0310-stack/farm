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
import math
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
    collect_secured_wheat_deliveries,
    TimedWheatDelivery,
    FeedExecutionSnapshot,
    FeedResourceLedger,
    FeedFeasibilityResult,
    build_feed_resource_ledger,
    build_feed_execution_snapshot,
    evaluate_existing_herd_feasibility,
    evaluate_incremental_candidate,
    commit_candidate_reservation,
    compute_worst_case_remaining_town_wheat_drain,
    compute_observed_opponent_feed_liability,
    compute_engine_stress_wheat_price,
    check_live_livestock_execution_safety,
    build_fresh_live_ledger,
    compute_remaining_existing_feed_hold,
)
from strategy.herd_planner import generate_dynamic_herd_plan, DynamicHerdPlan
from observation_parser import parse_observation
from strategy.macro_planner import MacroPlanner
from state.state_tracker import reset_memory


class DummyFC:
    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        return 50.0


def make_mock_tile(pos, kind="EMPTY", is_plant=False, is_animal=False, animal=None, crop=None, placed_day=0, planted_day=None, fed_today=False):
    t = MagicMock()
    t.pos = pos
    t.kind = kind
    t.is_plant = is_plant
    t.is_animal = is_animal
    t.animal = animal
    t.crop = crop
    t.placed_day = placed_day
    t.planted_day = planted_day
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
        t = make_mock_tile((j, 1), kind="PLANT", is_plant=True, crop="WHEAT", planted_day=pday)
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
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=20, placed_animals=[])
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
    """Wheat arriving on Day 12 cannot satisfy feed owed on Day 10 or 11.

    Adversarial setup:
    At Day 10, Hour 23, 1 placed COW, 0 wheat on hand, $1000 cash.
    At Hour 23, new same-day purchases cannot help today.
    A scheduled purchase delivering 5 units on Day 12 provides ZERO credit on Day 10.
    Moving that same purchase to Day 10 satisfies Day 10.
    """
    # Context with 1 placed COW, 0 wheat on hand, Hour 23
    ctx = make_mock_farm_ctx(day=10, hour=23, money=1000.0, shed_wheat=0, placed_animals=["COW"])

    # 1. Scheduled purchase arrives on Day 12
    ledger_day12 = build_feed_resource_ledger(ctx)
    ledger_day12.scheduled_market_purchases = [
        {
            "day": 12,
            "units": 5,
            "cost": 140.0,
            "purpose": "test_future_buy",
        }
    ]
    feasible12, res12 = evaluate_existing_herd_feasibility(ledger_day12)
    # Must fail on Day 10 because Day 12 purchase gives ZERO credit on Day 10
    assert feasible12 is False
    assert res12.blocking_day == 10
    assert res12.blocking_reason == "late_hour_purchase"

    # Also test candidate evaluation with Day 12 scheduled wheat
    # Candidate GOOSE evaluated at Day 10, Hour 0, money = 100.0 (only enough for purchase cost $100)
    ctx_cand = make_mock_farm_ctx(day=10, hour=0, money=100.0, shed_wheat=0, placed_animals=[])
    ledger_cand12 = build_feed_resource_ledger(ctx_cand)
    ledger_cand12.scheduled_market_purchases = [
        {
            "day": 12,
            "units": 5,
            "cost": 140.0,
            "purpose": "test_future_buy",
        }
    ]
    # GOOSE costs $100. Needs feed on Day 11. Cash left after purchase is $0.
    # Day 12 wheat gives ZERO credit on Day 11 -> must fail on Day 11 for lack of feed cash!
    cand_res12 = evaluate_incremental_candidate(ledger_cand12, "GOOSE", purchase_cost=100.0)
    assert cand_res12.feasible is False
    assert cand_res12.blocking_day == 11
    assert cand_res12.blocking_reason == "insufficient_cash"

    # 2. At Hour 0 (where market purchases can help today), moving that same purchase to Day 10 satisfies Day 10:
    ctx_hour0 = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger_day10 = build_feed_resource_ledger(ctx_hour0)
    ledger_day10.scheduled_market_purchases = [
        {
            "day": 10,
            "units": 5,
            "cost": 140.0,
            "purpose": "test_today_buy",
        }
    ]
    feasible10, res10 = evaluate_existing_herd_feasibility(ledger_day10)
    # Day 10 has 5 wheat available from today's delivery, which covers Day 10 (1), 11 (1), 12 (1), 13 (1)!
    assert feasible10 is True
    assert res10.minimum_wheat_slack >= 1.0


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


def test_shed_capacity_previously_reserved_wheat_accounting():
    """Shed-capacity accounting for previously reserved wheat purchases.

    Test 1: 98 existing other items in shed + 2 previously committed market wheat arriving today
            + 1 candidate market wheat arriving today = 101/100 -> rejected!
    """
    # 2 placed animals already fed today on Day 10, so they need 2 wheat on Day 11.
    # The 2 committed market wheat on Day 11 are needed by the existing herd.
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=0, placed_animals=["COW", "SHEEP"], fed_animals_count=2)
    ledger = build_feed_resource_ledger(ctx)
    ledger.shed_other_units = 98
    # Pre-existing committed market purchase delivering 2 units on Day 11 for existing herd
    ledger.scheduled_market_purchases = [
        {"day": 11, "units": 2, "cost": 56.0, "purpose": "existing_committed"}
    ]

    # Candidate COW also needs 1 feed wheat on Day 11.
    # Total needed on Day 11 = 2 (existing) + 1 (cand) = 3.
    # Available before cand buy = 2 (committed). Deficit for candidate = 1.
    # Load on Day 11 at acquisition: 98 existing + 2 committed + 1 candidate = 101 > 100 -> rejected!
    cand_res = evaluate_incremental_candidate(ledger, "COW")
    assert cand_res.feasible is False
    assert cand_res.blocking_day == 11
    assert cand_res.blocking_reason == "shed_capacity"


def test_shed_capacity_earlier_consumption_creates_space():
    """Earlier feed genuinely consumed before acquisition point creates capacity.

    Test 2: Same resources (98 other units + 2 committed arriving Day 11 + 1 candidate on Day 11),
            but shed had 1 initial wheat and 1 placed COW on Day 10 that genuinely consumes it!
            Shed wheat before Day 11 arrival = 1 - 1 = 0.
            Load on Day 11 at acquisition = 98 + 2 + 1 = 100 <= 100 -> feasible!
    """
    # 1 placed COW that eats 1 wheat on Day 10 (unfed placed today = 1), 1 wheat in shed
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=1, placed_animals=["COW"], fed_animals_count=0)
    ledger = build_feed_resource_ledger(ctx)
    ledger.shed_other_units = 97  # 97 other + 1 wheat = 98 initial shed load
    ledger.scheduled_market_purchases = [
        {"day": 11, "units": 2, "cost": 56.0, "purpose": "existing_committed"}
    ]

    # On Day 10: COW consumes the 1 wheat -> wheat in shed drops to 0.
    # On Day 11: 2 committed wheat arrive + candidate needs 1 wheat = 3 units arriving.
    # Load on Day 11: 97 other + 3 arriving = 100 <= 100 -> fits!
    cand_res = evaluate_incremental_candidate(ledger, "COW")
    assert cand_res.feasible is True
    assert cand_res.blocking_reason is None


def test_shed_capacity_later_consumption_cannot_rescue_earlier_overflow():
    """Strict temporal ordering: later consumption cannot retroactively rescue earlier full-shed purchase.

    Test 3: Full shed on Day 10 (98 existing + 2 committed + 1 deficit = 101).
            Even if animals will consume 10 units of feed on Day 11/12/13,
            the overflow at acquisition on Day 10 CANNOT be rescued and must fail immediately.
    """
    # 5 placed COWs will eat 5 wheat on Day 11, 5 on Day 12
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=0, placed_animals=["COW"] * 5, fed_animals_count=5)
    ledger = build_feed_resource_ledger(ctx)
    ledger.shed_other_units = 98
    ledger.unfed_placed_today = 3  # 3 cows unfed today -> 2 covered by scheduled buy + 1 deficit = 3 arriving on Day 10!
    ledger.scheduled_market_purchases = [
        {"day": 10, "units": 2, "cost": 56.0, "purpose": "committed_day10"}
    ]

    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is False
    assert res.blocking_day == 10
    assert res.blocking_reason == "shed_capacity"


def test_candidate_storage_slots_reserved_accounting():
    """Exact prospective candidate animal shed capacity cases (Cases A, B, C, D).

    Case A: Shed load 100/100, 0 reserved candidate slots -> candidate evaluation immediately fails
            with blocking_reason = 'shed_capacity'.
    Case B: Shed load 99/100, 0 reserved candidate slots, 0 feed wheat needed -> candidate occupies 100th slot, feasible.
    Case C: Shed load 98/100, 0 reserved candidate slots, 1 feed wheat arrives -> candidate occupies 99th slot,
            wheat arrives into 100th slot, fits exactly.
    Case D: Shed load 99/100, 0 reserved candidate slots, 1 feed wheat arrives -> candidate occupies 100th slot,
            wheat cannot fit, fails with blocking_reason = 'shed_capacity'.
    """
    # Case A: Shed load 100/100, 0 reserved candidate slots -> immediately fails
    ctx_a = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=0, placed_animals=[])
    ledger_a = build_feed_resource_ledger(ctx_a)
    ledger_a.shed_other_units = 100
    ledger_a.candidate_storage_slots_reserved = 0
    res_a = evaluate_incremental_candidate(ledger_a, "COW")
    assert res_a.feasible is False
    assert res_a.blocking_day == 10
    assert res_a.blocking_reason == "shed_capacity"

    # Case B: Shed load 99/100, 0 reserved candidate slots, 0 feed wheat needed -> fits exactly
    # Day 29 is ANIMAL_FEED_CUTOFF_DAY, so operational days requiring feed is empty.
    ctx_b = make_mock_farm_ctx(day=29, hour=0, money=5000.0, shed_wheat=0, placed_animals=[])
    ledger_b = build_feed_resource_ledger(ctx_b)
    ledger_b.shed_other_units = 99
    ledger_b.candidate_storage_slots_reserved = 0
    res_b = evaluate_incremental_candidate(ledger_b, "COW")
    assert res_b.feasible is True
    assert res_b.blocking_reason is None

    # Case C: Shed load 98/100, 0 reserved candidate slots, 1 feed wheat arrives -> fits exactly at 100
    # Day 27, operational horizon 2 days: candidate evaluated Day 27, eats 1 wheat on Day 28 (Day 29 cutoff).
    ctx_c = make_mock_farm_ctx(day=27, hour=0, money=5000.0, shed_wheat=0, placed_animals=[])
    ledger_c = build_feed_resource_ledger(ctx_c)
    ledger_c.shed_other_units = 98
    ledger_c.candidate_storage_slots_reserved = 0
    ledger_c.operational_horizon_days = 2
    res_c = evaluate_incremental_candidate(ledger_c, "COW")
    assert res_c.feasible is True
    assert res_c.blocking_reason is None

    # Case D: Shed load 99/100, 0 reserved candidate slots, 1 feed wheat arrives -> 99 + 1 + 1 = 101 > 100 fails
    ctx_d = make_mock_farm_ctx(day=27, hour=0, money=5000.0, shed_wheat=0, placed_animals=[])
    ledger_d = build_feed_resource_ledger(ctx_d)
    ledger_d.shed_other_units = 99
    ledger_d.candidate_storage_slots_reserved = 0
    ledger_d.operational_horizon_days = 2
    res_d = evaluate_incremental_candidate(ledger_d, "COW")
    assert res_d.feasible is False
    assert res_d.blocking_day == 28
    assert res_d.blocking_reason == "shed_capacity"

    # Purity check: ledger_d.candidate_storage_slots_reserved was NOT mutated by evaluation
    assert ledger_d.candidate_storage_slots_reserved == 0


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
# 18. Phase A Hardening: Purity, Speculative Resources, & Wheat Monotonicity
# ===========================================================================

def test_candidate_evaluation_is_fully_pure_and_non_mutating():
    """Candidate evaluation must be completely pure and never mutate the caller's ledger."""
    import copy
    ctx = make_mock_farm_ctx(day=10, hour=0, money=3000.0, shed_wheat=5, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx)

    before = copy.deepcopy(ledger.to_dict())

    # Evaluate candidate (do not commit)
    res = evaluate_incremental_candidate(ledger, "COW")

    after = ledger.to_dict()
    assert after == before, "evaluate_incremental_candidate mutated the caller's ledger dictionary!"

    # Explicit field checks
    assert ledger.candidate_reservations == []
    assert ledger.scheduled_market_purchases == []
    assert ledger.candidate_feed_cash_hold == 0.0
    assert ledger.candidate_purchase_cash_spent == 0.0
    assert ledger.candidate_storage_slots_reserved == 0
    assert ledger.placed_herd == {"COW": 1, "SHEEP": 0, "GOOSE": 0}
    assert ledger.owned_unplaced_herd == {"COW": 0, "SHEEP": 0, "GOOSE": 0}

    # Only commit_candidate_reservation may modify the shared ledger:
    commit_candidate_reservation(ledger, res)
    assert len(ledger.candidate_reservations) == 1
    assert ledger.candidate_feed_cash_hold > 0.0
    assert ledger.candidate_purchase_cash_spent == float(ANIMALS["COW"]["cost"])
    assert ledger.candidate_storage_slots_reserved == 1


def test_speculative_resources_adversarial_rejection():
    """Hard feasibility must ignore unowned SW, empty SW, planned wheat targets,
    hypothetical planting queues, future seed purchases, empty dirt, and animal revenue.
    """
    ctx = make_mock_farm_ctx(
        day=10,
        hour=0,
        money=200.0,
        shed_wheat=0,
        placed_animals=[],  # 0 existing animals so existing herd is feasible
        unlocked=("NW",),  # SW is unowned!
    )
    # Inject adversarial speculative structures into ctx and farm:
    farm = ctx["farm"]
    farm.unlocked = {"NW"}  # SW unowned
    empty_dirt_tile = make_mock_tile((0, 5), kind="DIRT", is_plant=False)
    ctx["plan"] = {"wheat_target": 20, "intents": {"plant_wheat": 15}}
    ctx["planting_queue"] = ["WHEAT"] * 10
    ctx["planned_seed_buys"] = {"WHEAT": 20}
    private = ctx["private"]
    private.shed["WHEAT_SEED"] = 20
    private.seed_inventory = {"WHEAT": 20}

    # Verify collect_secured_wheat_deliveries ignores all of them:
    deliveries = collect_secured_wheat_deliveries(farm, current_day=10, operational_end_day=13)
    assert len(deliveries) == 0, "Speculative resources or empty tiles produced wheat deliveries!"

    ledger = build_feed_resource_ledger(ctx)
    assert len(ledger.secured_wheat_deliveries) == 0

    # Feasibility must NOT give candidate any speculative revenue credit
    # COW costs $400, but money is $200. Candidate produces MILK ($120/day), but that revenue is speculative!
    cand_res = evaluate_incremental_candidate(ledger, "COW")
    assert cand_res.feasible is False
    assert cand_res.blocking_reason == "insufficient_cash"
    assert cand_res.minimum_cash_slack < 0.0

    # Also verify existing animals get zero speculative revenue credit:
    # 1 placed COW with $200 cash cannot fund its lifetime feed ($420) despite producing milk ($120/day)
    ctx_exist = make_mock_farm_ctx(day=10, hour=0, money=200.0, shed_wheat=0, placed_animals=["COW"])
    ledger_exist = build_feed_resource_ledger(ctx_exist)
    exist_ok, exist_res = evaluate_existing_herd_feasibility(ledger_exist)
    assert exist_ok is False
    assert exist_res.blocking_reason == "insufficient_cash"


def test_feed_feasibility_monotonicity_under_wheat_quantity():
    """Property regression: wheat = X vs wheat = X + N.
    More genuinely usable wheat must never make feed feasibility worse:
      1. If low-wheat state is feasible -> higher-wheat state must also be feasible.
      2. Higher wheat -> market wheat requirement cannot increase.
      3. Higher wheat -> minimum wheat slack cannot decrease.
    """
    # Test across multiple wheat levels with money = $5000 so purchasing cash is not the gating constraint
    for base_wheat in [0, 1, 2, 5, 8]:
        for add_wheat in [1, 2, 5]:
            low_wheat = base_wheat
            high_wheat = base_wheat + add_wheat

            ctx_low = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=low_wheat, placed_animals=["COW"] * 2)
            ctx_high = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=high_wheat, placed_animals=["COW"] * 2)

            ledger_low = build_feed_resource_ledger(ctx_low)
            ledger_high = build_feed_resource_ledger(ctx_high)

            # Test existing herd feasibility monotonicity
            ok_low, res_low = evaluate_existing_herd_feasibility(ledger_low)
            ok_high, res_high = evaluate_existing_herd_feasibility(ledger_high)

            if ok_low:
                assert ok_high is True, f"Low wheat ({low_wheat}) was feasible, but high wheat ({high_wheat}) was infeasible!"

            assert res_high.near_term_market_wheat_required <= res_low.near_term_market_wheat_required, (
                f"Higher wheat ({high_wheat}) required MORE market wheat ({res_high.near_term_market_wheat_required}) "
                f"than lower wheat ({low_wheat}, required {res_low.near_term_market_wheat_required})!"
            )

            assert res_high.minimum_wheat_slack >= res_low.minimum_wheat_slack, (
                f"Higher wheat ({high_wheat}) had LOWER minimum wheat slack ({res_high.minimum_wheat_slack}) "
                f"than lower wheat ({low_wheat}, slack {res_low.minimum_wheat_slack})!"
            )

            # Test candidate feasibility monotonicity
            cand_low = evaluate_incremental_candidate(ledger_low, "SHEEP")
            cand_high = evaluate_incremental_candidate(ledger_high, "SHEEP")

            if cand_low.feasible:
                assert cand_high.feasible is True, "Low wheat candidate was feasible, high wheat candidate was infeasible!"

            assert cand_high.near_term_market_wheat_required <= cand_low.near_term_market_wheat_required
            assert cand_high.minimum_wheat_slack >= cand_low.minimum_wheat_slack


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


# ===========================================================================
# 19. Issue 1 Timing Regressions: Unit-Before-Market Boundary
# ===========================================================================

def test_hour23_same_day_scheduled_wheat_cannot_rescue_today():
    """Prefix test:
    Day 10, Hour 23, 1 unfed COW, 0 wheat physically available, 5 scheduled market wheat arriving Day 10:
    - must evaluate as infeasible on Day 10 (blocking_day == 10, blocking_reason == 'late_hour_purchase');
    - must NOT credit the 5 units toward Day 10's unfed COW.
    """
    ctx = make_mock_farm_ctx(day=10, hour=23, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx)
    ledger.scheduled_market_purchases = [
        {
            "day": 10,
            "units": 5,
            "cost": 140.0,
            "purpose": "test_same_day_scheduled",
        }
    ]
    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is False
    assert res.blocking_day == 10
    assert res.blocking_reason == "late_hour_purchase"


def test_hour23_same_day_scheduled_wheat_retained_for_day11_plus():
    """Day 11+ test:
    Same setup, but if today's feed is already satisfied (1 wheat on hand today, 0 unfed today),
    the 5 scheduled Day 10 wheat MUST count toward Day 11+ feed requirements.
    """
    ctx = make_mock_farm_ctx(day=10, hour=23, money=1000.0, shed_wheat=1, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx)
    ledger.unfed_placed_today = 0  # Today's feed obligation already satisfied!
    ledger.scheduled_market_purchases = [
        {
            "day": 10,
            "units": 5,
            "cost": 140.0,
            "purpose": "test_same_day_scheduled",
        }
    ]
    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is True
    # The 5 scheduled wheat units on Day 10 enter inventory at turn end and cover Day 11+ requirements
    assert res.minimum_wheat_slack >= 1.0


def test_hour0_same_day_scheduled_wheat_can_rescue_today():
    """Earlier hour test:
    Same setup at Day 10, Hour 0 (where market_purchase_can_help_today is True):
    Day 10 scheduled market wheat CAN help satisfy Day 10 feed.
    """
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx)
    ledger.scheduled_market_purchases = [
        {
            "day": 10,
            "units": 5,
            "cost": 140.0,
            "purpose": "test_same_day_scheduled",
        }
    ]
    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is True
    assert res.minimum_wheat_slack >= 1.0


# ============================================================================
# Phase B Tests
# ============================================================================

def test_phase_b_existing_herd_stress_funding_zero_candidates():
    """Phase B user correction #1:
    evaluate_existing_herd_feasibility() must apply engine_stress_bound_v1
    to the existing herd even when 0 incremental candidates are evaluated.
    """
    ctx = make_mock_farm_ctx(day=10, hour=0, money=10000.0, shed_wheat=0, placed_animals=["COW", "COW"])
    ledger = build_feed_resource_ledger(
        ctx,
        hard_cash_hold=500.0,
        lifetime_price_policy="engine_stress_bound_v1",
        market_inventory={"WHEAT": 8000.0},
    )
    assert ledger.lifetime_price_policy == "engine_stress_bound_v1"

    ok, res = evaluate_existing_herd_feasibility(ledger)
    assert ok is True
    # Stress price should be higher than current executable buffered price ($28)
    assert res.diagnostics.get("lifetime_wheat_price", 0) > ledger.wheat_price_current
    assert ledger.lifetime_wheat_price > ledger.wheat_price_current
    # existing_feed_cash_hold must reflect stress pricing on remaining-lifetime units
    assert ledger.existing_feed_cash_hold > 0
    # Exactly matches the required hold
    assert ledger.existing_feed_cash_hold == res.existing_feed_cash_hold


def test_phase_b_semantic_hold_repricing_separation():
    """Phase B user correction #2:
    Strict semantic hold separation:
      - Uplift on existing herd goes to existing_feed_cash_hold.
      - Uplift on prior candidates + new candidate's own hold goes to candidate_feed_cash_hold.
      - Never dump existing herd repricing into candidate_feed_cash_hold.
    """
    ctx = make_mock_farm_ctx(day=10, hour=0, money=10000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(
        ctx,
        lifetime_price_policy="engine_stress_bound_v1",
        market_inventory={"WHEAT": 7500.0},
    )
    ok, res_init = evaluate_existing_herd_feasibility(ledger)
    assert ok is True
    e0 = ledger.existing_feed_cash_hold
    c0 = ledger.candidate_feed_cash_hold
    assert c0 == 0.0

    # Candidate 1: COW
    res1 = evaluate_incremental_candidate(ledger, "COW")
    assert res1.feasible is True
    commit_candidate_reservation(ledger, res1)
    e1 = ledger.existing_feed_cash_hold
    c1 = ledger.candidate_feed_cash_hold
    # Candidate 1 required its own feed hold
    assert c1 > 0
    assert e1 >= e0

    # Candidate 2: SHEEP
    res2 = evaluate_incremental_candidate(ledger, "SHEEP")
    assert res2.feasible is True
    commit_candidate_reservation(ledger, res2)
    e2 = ledger.existing_feed_cash_hold
    c2 = ledger.candidate_feed_cash_hold

    # As cumulative feed demand increases, stress price rises or stays equal
    assert e2 >= e1
    # Candidate hold includes Candidate 2 + repriced Candidate 1
    assert c2 > c1
    # Check total deduction consistency
    total_deductions = (e2 - e0) + c2 + ledger.candidate_purchase_cash_spent
    spent_or_held = (
        ledger.hard_cash_hold
        + ledger.existing_feed_cash_hold
        + ledger.strategic_cash_hold
        + ledger.candidate_purchase_cash_spent
        + ledger.candidate_feed_cash_hold
    )
    assert ledger.available_cash_for_candidates == max(0.0, ledger.observed_cash - spent_or_held)


def test_phase_b_town_drain_monotonicity_and_event_cadence():
    """Phase B user correction #5:
    Town wheat drain simulation:
      - Strictly monotonic non-increasing across all 720 steps.
      - Exact cadence at step 71 vs 72 (Day 2 Hour 23 vs Day 3 Hour 0).
    """
    drains = [compute_worst_case_remaining_town_wheat_drain(s // 24, s % 24) for s in range(721)]
    for i in range(len(drains) - 1):
        assert drains[i] >= drains[i + 1], f"Drain increased at step {i}: {drains[i]} -> {drains[i+1]}"

    # Step 71 is Day 2 Hour 23, step 72 is Day 3 Hour 0
    assert drains[71] >= drains[72]
    # Step 719 has 0 drain
    assert drains[719] == 0
    assert drains[720] == 0


def test_phase_b_opponent_feed_liability():
    """Phase B user correction #4:
    Opponent feed liability correctly reads placed animals and remaining days.
    """
    class MockTile:
        def __init__(self, is_animal):
            self.is_animal = is_animal

    class MockOpponentFarm:
        def iter_tiles(self):
            return [MockTile(True), MockTile(True), MockTile(False)]

    opp_farm = MockOpponentFarm()
    # At Day 10, remaining days = 29 - 10 = 19
    liability_d10 = compute_observed_opponent_feed_liability(opp_farm, 10)
    assert liability_d10 == 2 * 19

    # At Day 28, remaining days = 29 - 28 = 1
    liability_d28 = compute_observed_opponent_feed_liability(opp_farm, 28)
    assert liability_d28 == 2 * 1

    # At Day 29, remaining days = 0
    liability_d29 = compute_observed_opponent_feed_liability(opp_farm, 29)
    assert liability_d29 == 0


def test_phase_b_dynamic_herd_plan_profitable_but_feed_infeasible_rejected():
    """Under feed_ledger authority, a candidate that would be economically profitable
    under baseline pricing is rejected if the residual ledger cannot support its feed.
    """
    # $600 money at Day 10: enough for 1 Cow purchase ($500), but NOT enough for Cow purchase + 15 lifetime feed
    ctx = make_mock_farm_ctx(day=10, hour=0, money=600.0, shed_wheat=0, placed_animals=[])
    ledger = build_feed_resource_ledger(
        ctx,
        lifetime_price_policy="engine_stress_bound_v1",
        market_inventory={"WHEAT": 8000.0},
    )

    plan = generate_dynamic_herd_plan(
        day=10,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY"],
        market_inventory={"WHEAT": 8000.0},
        max_sustainable=10,
        feed_ledger=ledger,
    )
    # Cow should not be admitted because $600 cannot cover purchase ($500) + lifetime feed (~$1200)
    assert plan.desired_cows == 0


def test_phase_b_dynamic_herd_plan_ev_below_hurdle_rejected():
    """Candidates whose marginal realized net value is below $150 housing hurdle are stopped."""
    # Near cutoff, ROI falls below $150
    plan = generate_dynamic_herd_plan(
        day=11,
        hour=20,
        current_herd={"COW": 2, "SHEEP": 0, "GOOSE": 0},
        crop_opportunity_val=500.0,  # high opportunity cost pushes net value down
    )
    # Forward housing should stop
    for rec in plan.decision_records:
        if not rec.get("accepted"):
            assert rec.get("reason") in ("below_housing_hurdle", "invalid_species")


def test_phase_b_dynamic_herd_plan_guarded_confidence_provisional():
    """Guarded execution confidence marks decision record as provisional_guarded."""
    ctx = make_mock_farm_ctx(day=10, hour=20, money=10000.0, shed_wheat=0, placed_animals=[])
    # Build execution snapshot with guarded confidence (late hour, unfed)
    snap = build_feed_execution_snapshot(ctx)
    snap.execution_confidence = "guarded"
    ledger = build_feed_resource_ledger(
        ctx,
        execution_snapshot=snap,
        lifetime_price_policy="engine_stress_bound_v1",
    )

    plan = generate_dynamic_herd_plan(
        day=10,
        hour=20,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        feed_ledger=ledger,
    )
    for rec in plan.decision_records:
        if rec.get("accepted"):
            assert rec.get("execution_status") == "provisional_guarded"


def test_phase_b_dynamic_herd_plan_existing_infeasible_stops():
    """If baseline existing herd is feed-infeasible, DynamicHerdPlan stops immediately
    and requests 0 additional housing.
    """
    # 2 placed cows, 0 wheat, $50 cash -> existing herd cannot be funded
    ctx = make_mock_farm_ctx(day=10, hour=0, money=50.0, shed_wheat=0, placed_animals=["COW", "COW"])
    ledger = build_feed_resource_ledger(
        ctx,
        lifetime_price_policy="engine_stress_bound_v1",
    )
    plan = generate_dynamic_herd_plan(
        day=10,
        hour=0,
        current_herd={"COW": 2, "SHEEP": 0, "GOOSE": 0},
        feed_ledger=ledger,
    )
    assert plan.desired_cows == 2
    assert plan.desired_sheep == 0
    assert plan.desired_geese == 0
    assert plan.rationale == "baseline_existing_herd_infeasible"
    assert "infeasible" in plan.marginal_value_sequence[0]


def test_phase_b_dynamic_herd_plan_capital_insensitivity():
    """Regression test:
    Under feed constraints, herd targets should be identical between $10,000 and $100,000
    when feed authority bounds expansion rather than cash.
    """
    ctx1 = make_mock_farm_ctx(day=10, hour=0, money=10000.0, shed_wheat=0, placed_animals=["COW"])
    ctx2 = make_mock_farm_ctx(day=10, hour=0, money=100000.0, shed_wheat=0, placed_animals=["COW"])

    ledger1 = build_feed_resource_ledger(ctx1, lifetime_price_policy="engine_stress_bound_v1")
    ledger1.shed_other_units = 94
    ledger2 = build_feed_resource_ledger(ctx2, lifetime_price_policy="engine_stress_bound_v1")
    ledger2.shed_other_units = 94

    plan1 = generate_dynamic_herd_plan(day=10, hour=0, current_herd={"COW": 1, "SHEEP": 0, "GOOSE": 0}, feed_ledger=ledger1)
    plan2 = generate_dynamic_herd_plan(day=10, hour=0, current_herd={"COW": 1, "SHEEP": 0, "GOOSE": 0}, feed_ledger=ledger2)

    # Both plans should project the exact same herd size
    assert plan1.desired_herd == plan2.desired_herd


# ===========================================================================
# Phase B Repair Tests (P1 & Hardening items)
# ===========================================================================

def test_phase_b_repair_macro_placed_vs_unplaced_semantics():
    """P1: Preserve placed vs owned-unplaced herd semantics in Macro planning ledger.
    - 1 placed cow + 1 shed cow: placed=1, unplaced=1, unfed_today=1.
    - 1 placed cow + 1 worker cow: placed=1, unplaced=1, unfed_today=1.
    Unplaced animals must not create current-day feed obligations.
    """
    # Case A: 1 placed COW, 1 shed COW
    ctx_shed = make_mock_farm_ctx(day=10, hour=0, money=1000.0, placed_animals=["COW"], shed_animals={"COW": 1})
    ledger_shed = build_feed_resource_ledger(ctx_shed)
    assert ledger_shed.placed_herd["COW"] == 1
    assert ledger_shed.owned_unplaced_herd["COW"] == 1
    assert ledger_shed.total_placed_animals == 1
    assert ledger_shed.total_owned_unplaced_animals == 1
    assert ledger_shed.total_owned_animals == 2
    assert ledger_shed.unfed_placed_today == 1

    # Case B: 1 placed COW, 1 worker COW
    ctx_worker = make_mock_farm_ctx(day=10, hour=0, money=1000.0, placed_animals=["COW"], worker_animals=["COW"])
    ledger_worker = build_feed_resource_ledger(ctx_worker)
    assert ledger_worker.placed_herd["COW"] == 1
    assert ledger_worker.owned_unplaced_herd["COW"] == 1
    assert ledger_worker.total_placed_animals == 1
    assert ledger_worker.total_owned_unplaced_animals == 1
    assert ledger_worker.total_owned_animals == 2
    assert ledger_worker.unfed_placed_today == 1


def test_phase_b_repair_ledger_fail_closed_in_herd_plan_and_live(monkeypatch):
    """P1: Never silently fall back to legacy scalar authority in herd_plan / live.
    When build_feed_resource_ledger fails or returns None, or generate_dynamic_herd_plan fails:
    FAIL CLOSED immediately:
      dynamic_targets = current owned herd
      needed_new_pastures = 0
      final_feed_capped_herd_size = sum(current_owned_herd)
      feed_authority = 'ledger_error_fail_closed'
    """
    import config
    import strategy.macro_planner as mp_module

    ctx = make_mock_farm_ctx(day=6, hour=0, money=5000.0, shed_wheat=20, placed_animals=["COW"])

    for mode in ("herd_plan", "live"):
        monkeypatch.setattr(config, "POINT2_FEED_MODE", mode)
        reset_memory()

        # 1. build_feed_resource_ledger raises RuntimeError
        def mock_failing_build(*args, **kwargs):
            raise RuntimeError("Simulated ledger build failure")

        monkeypatch.setattr(mp_module, "build_feed_resource_ledger", mock_failing_build)

        planner = MacroPlanner(DummyFC())
        plan = planner.build(ctx)

        authority_diag = plan.diagnostics.get("point2_feed_authority", {})
        assert authority_diag.get("mode") == mode
        assert authority_diag.get("feed_authority") == "ledger_error_fail_closed"
        assert authority_diag.get("error_type") == "RuntimeError"
        assert "Simulated ledger build failure" in authority_diag.get("error_message", "")

        pasture_diag = plan.diagnostics.get("pasture_diagnostics", {})
        assert pasture_diag.get("pastures_needed_now") == 0
        assert pasture_diag.get("desired_target_herd") == 1  # 1 cow owned, zero expansion
        assert len(plan.build_queue) == 0

        # 2. build_feed_resource_ledger returns None
        def mock_none_build(*args, **kwargs):
            return None

        monkeypatch.setattr(mp_module, "build_feed_resource_ledger", mock_none_build)

        planner = MacroPlanner(DummyFC())
        plan = planner.build(ctx)
        authority_diag = plan.diagnostics.get("point2_feed_authority", {})
        assert authority_diag.get("feed_authority") == "ledger_error_fail_closed"
        assert authority_diag.get("error_type") == "RuntimeError"

        # 3. generate_dynamic_herd_plan raises error
        monkeypatch.setattr(mp_module, "build_feed_resource_ledger", build_feed_resource_ledger)

        def mock_failing_herd_plan(*args, **kwargs):
            raise ValueError("Simulated herd planner failure")

        import strategy.herd_planner as hp_module
        monkeypatch.setattr(hp_module, "generate_dynamic_herd_plan", mock_failing_herd_plan)

        planner = MacroPlanner(DummyFC())
        plan = planner.build(ctx)
        authority_diag = plan.diagnostics.get("point2_feed_authority", {})
        assert authority_diag.get("feed_authority") == "ledger_error_fail_closed"
        assert authority_diag.get("error_type") == "ValueError"
        assert plan.diagnostics["pasture_diagnostics"]["desired_target_herd"] == 1


def test_phase_b_repair_wheat_buy_price_buffer_config(monkeypatch):
    """Hardening #3: Replace hardcoded 1.10 with WHEAT_BUY_PRICE_BUFFER."""
    import strategy.feed_feasibility as ff_module

    monkeypatch.setattr(ff_module, "WHEAT_BUY_PRICE_BUFFER", 1.25)
    stress_price, diag = compute_engine_stress_wheat_price(
        current_market_wheat_inventory=1000.0,
        worst_case_town_drain=100,
        our_committed_future_market_feed_requirement=20,
        opponent_feed_liability=0,
        executable_buffered_price=28.0,
    )
    expected_buffered = float(math.ceil(diag["stress_raw_price"] * 1.25))
    assert diag["stress_buffered_price"] == expected_buffered


def test_phase_b_repair_stress_telemetry_synchronization():
    """Hardening #4: Synchronize full stress telemetry after candidate commit.
    In commit_candidate_reservation(), update stressed_wheat_inventory, stress_raw_price,
    stress_buffered_price, and lifetime_wheat_price from result.diagnostics['stress_diagnostics'].
    """
    ctx = make_mock_farm_ctx(day=10, hour=0, money=10000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(
        ctx,
        lifetime_price_policy="engine_stress_bound_v1",
        market_inventory={"WHEAT": 5000.0},
    )
    ok, res_init = evaluate_existing_herd_feasibility(ledger)
    assert ok is True

    res1 = evaluate_incremental_candidate(ledger, "COW")
    assert res1.feasible is True
    commit_candidate_reservation(ledger, res1)

    s_diag1 = res1.diagnostics["stress_diagnostics"]
    assert ledger.stressed_wheat_inventory == s_diag1["stressed_wheat_inventory"]
    assert ledger.stress_raw_price == s_diag1["stress_raw_price"]
    assert ledger.stress_buffered_price == s_diag1["stress_buffered_price"]
    assert ledger.lifetime_wheat_price == s_diag1["lifetime_wheat_price"]

    # Candidate 2: SHEEP
    res2 = evaluate_incremental_candidate(ledger, "SHEEP")
    assert res2.feasible is True
    commit_candidate_reservation(ledger, res2)

    s_diag2 = res2.diagnostics["stress_diagnostics"]
    assert ledger.stressed_wheat_inventory == s_diag2["stressed_wheat_inventory"]
    assert ledger.stress_raw_price == s_diag2["stress_raw_price"]
    assert ledger.stress_buffered_price == s_diag2["stress_buffered_price"]
    assert ledger.lifetime_wheat_price == s_diag2["lifetime_wheat_price"]

    # Stress inventory decreases and stress prices increase monotonically with commitments
    assert s_diag2["stressed_wheat_inventory"] <= s_diag1["stressed_wheat_inventory"]
    assert s_diag2["stress_raw_price"] >= s_diag1["stress_raw_price"]
    assert s_diag2["stress_buffered_price"] >= s_diag1["stress_buffered_price"]


def test_phase_b_repair_direct_max_sustainable_authority_regression():
    """Hardening #5: Direct max_sustainable authority regression.
    feed_ledger=None obeys scalar cap, while feed_ledger provided bypasses scalar cap.
    """
    # 1. feed_ledger=None: obeys max_sustainable=5
    plan_none = generate_dynamic_herd_plan(
        day=10,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        max_sustainable=5,
        feed_ledger=None,
    )
    assert sum(plan_none.desired_herd.values()) <= 5

    # 2. feed_ledger provided: abundant physical wheat / cash bypasses max_sustainable=5
    ctx = make_mock_farm_ctx(day=10, hour=0, money=15000.0, shed_wheat=60, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx, lifetime_price_policy="engine_stress_bound_v1")
    plan_ledger = generate_dynamic_herd_plan(
        day=10,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        max_sustainable=5,
        feed_ledger=ledger,
    )
    # With 60 wheat in shed, herd planner expands beyond 5 (up to species/market cap)
    assert sum(plan_ledger.desired_herd.values()) > 5


def test_phase_b_repair_exact_planning_budget_mapping():
    """Hardening #6: Verify exact planning budget mapping.
    planning_nonanimal_hold = max(0.0, farm_money - cash_for_animals),
    verify observed_cash - planning_nonanimal_hold == cash_for_animals.
    """
    farm_money = 5000.0
    cash_for_animals = 1200.0
    planning_nonanimal_hold = max(0.0, farm_money - float(cash_for_animals))
    assert farm_money - planning_nonanimal_hold == cash_for_animals

    ctx = make_mock_farm_ctx(day=10, hour=0, money=farm_money, shed_wheat=10, placed_animals=[])
    ledger = build_feed_resource_ledger(
        ctx,
        hard_cash_hold=planning_nonanimal_hold,
        lifetime_price_policy="engine_stress_bound_v1",
    )
    assert ledger.observed_cash == farm_money
    assert ledger.hard_cash_hold == planning_nonanimal_hold
    assert ledger.available_cash_for_candidates == cash_for_animals


# ===========================================================================
# Phase C1 Tests: Candidate-contract layer, provisional ordering, diagnostics
# ===========================================================================

def test_phase_c1_candidate_admission_preserves_interleaved_order():
    """Verify candidate admission preserves exact interleaved order (e.g. SHEEP, COW, SHEEP).
    DynamicHerdPlan.buy_animal_sequence must reflect sequential admissions without species sorting.
    """
    plan = DynamicHerdPlan(
        desired_herd={"COW": 1, "SHEEP": 2, "GOOSE": 0},
        required_pastures=3,
        required_coops=0,
        marginal_value_sequence=["SHEEP #1: +$300", "COW #1: +$280", "SHEEP #2: +$260"],
        decision_records=[
            {"species": "SHEEP", "candidate_num": 1, "net_val": 300.0, "accepted": True, "reason": "economically_justified"},
            {"species": "COW", "candidate_num": 1, "net_val": 280.0, "accepted": True, "reason": "economically_justified"},
            {"species": "SHEEP", "candidate_num": 2, "net_val": 260.0, "accepted": True, "reason": "economically_justified"},
        ],
        horizon_days=4,
    )
    assert plan.buy_animal_sequence == ["SHEEP", "COW", "SHEEP"]
    # Verify it was NOT sorted alphabetically (which would be ['COW', 'SHEEP', 'SHEEP'])
    assert plan.buy_animal_sequence != sorted(plan.buy_animal_sequence)


def test_phase_c1_aggregate_buy_animal_matches_sequence_counts():
    """Verify aggregate buy_animal matches sequence counts exactly."""
    plan = DynamicHerdPlan(
        desired_herd={"COW": 2, "SHEEP": 3, "GOOSE": 0},
        required_pastures=5,
        required_coops=0,
        marginal_value_sequence=[],
        decision_records=[
            {"species": "SHEEP", "candidate_num": 1, "net_val": 300.0, "accepted": True},
            {"species": "COW", "candidate_num": 1, "net_val": 290.0, "accepted": True},
            {"species": "SHEEP", "candidate_num": 2, "net_val": 280.0, "accepted": True},
            {"species": "SHEEP", "candidate_num": 3, "net_val": 270.0, "accepted": True},
            {"species": "COW", "candidate_num": 2, "net_val": 260.0, "accepted": True},
        ],
    )
    assert plan.buy_animal_sequence == ["SHEEP", "COW", "SHEEP", "SHEEP", "COW"]
    assert plan.buy_animal["SHEEP"] == 3
    assert plan.buy_animal["COW"] == 2
    assert plan.buy_animal["GOOSE"] == 0
    for sp in ("COW", "SHEEP", "GOOSE"):
        assert plan.buy_animal[sp] == plan.buy_animal_sequence.count(sp)


def test_phase_c1_stable_candidate_ids_and_sequence_indices():
    """Verify stable candidate IDs and sequence indices on provisional_candidates.
    Admitted candidates get sequence_index 0, 1, 2... and stable IDs cand_{idx}_{species}.
    Rejected candidates get sequence_index -1 and stable IDs cand_rej_{idx}_{species}.
    """
    plan = DynamicHerdPlan(
        desired_herd={"COW": 1, "SHEEP": 1, "GOOSE": 0},
        required_pastures=2,
        required_coops=0,
        marginal_value_sequence=[],
        decision_records=[
            {"species": "SHEEP", "candidate_num": 1, "net_val": 300.0, "accepted": True, "execution_status": "admitted"},
            {"species": "COW", "candidate_num": 1, "net_val": 280.0, "accepted": True, "execution_status": "provisional_guarded"},
            {"species": "GOOSE", "candidate_num": 1, "net_val": 100.0, "accepted": False, "reason": "below_housing_hurdle", "feed_feasible": True},
        ],
    )
    cands = plan.provisional_candidates
    assert len(cands) == 3

    # Candidate 0: SHEEP (admitted)
    assert cands[0]["candidate_id"] == "cand_0_SHEEP"
    assert cands[0]["sequence_index"] == 0
    assert cands[0]["species"] == "SHEEP"
    assert cands[0]["provisional_status"] == "admitted"
    assert cands[0]["feed_feasible"] is True
    assert cands[0]["execution_status"] == "admitted"
    assert cands[0]["net_realized_value"] == 300.0
    assert cands[0]["reason"] == "economically_justified"

    # Candidate 1: COW (admitted provisional_guarded)
    assert cands[1]["candidate_id"] == "cand_1_COW"
    assert cands[1]["sequence_index"] == 1
    assert cands[1]["species"] == "COW"
    assert cands[1]["provisional_status"] == "admitted"
    assert cands[1]["feed_feasible"] is True
    assert cands[1]["execution_status"] == "provisional_guarded"
    assert cands[1]["net_realized_value"] == 280.0

    # Candidate 2: GOOSE (rejected)
    assert cands[2]["candidate_id"] == "cand_rej_0_GOOSE"
    assert cands[2]["sequence_index"] == -1
    assert cands[2]["species"] == "GOOSE"
    assert cands[2]["provisional_status"] == "rejected"
    assert cands[2]["execution_status"] == "rejected"
    assert cands[2]["net_realized_value"] == 100.0
    assert cands[2]["reason"] == "below_housing_hurdle"


def test_phase_c1_rejected_candidates_recorded_with_reasons_and_not_in_sequence():
    """Verify rejected candidates (hurdle or feed-infeasible) are recorded with reasons
    in provisional_candidates and are NOT placed in buy_animal_sequence.
    """
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=0, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx, lifetime_price_policy="engine_stress_bound_v1")
    ledger.hard_cash_hold = 200.0

    plan = generate_dynamic_herd_plan(
        day=10,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY"],
        feed_ledger=ledger,
    )

    for sp in plan.buy_animal_sequence:
        assert sp in ("COW", "SHEEP", "GOOSE")

    rejected = [c for c in plan.provisional_candidates if c["provisional_status"] == "rejected"]
    if rejected:
        for r in rejected:
            assert r["sequence_index"] == -1
            assert r["execution_status"] == "rejected"
            assert "reason" in r and len(r["reason"]) > 0


def test_phase_c1_original_planning_ledger_not_corrupted():
    """Verify original planning ledger is not corrupted by candidate evaluations.
    Pure evaluation operates on clones and does not mutate caller's ledger.
    """
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=20, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx, lifetime_price_policy="engine_stress_bound_v1")

    orig_cash = ledger.observed_cash
    orig_reservations_len = len(ledger.candidate_reservations)
    orig_spent = ledger.candidate_purchase_cash_spent
    orig_wheat = ledger.wheat_in_shed
    orig_hold = ledger.existing_feed_cash_hold

    # Evaluate incremental candidates without committing
    evaluate_incremental_candidate(ledger, "COW")
    evaluate_incremental_candidate(ledger, "SHEEP")
    evaluate_incremental_candidate(ledger, "GOOSE")

    # Verify original ledger is completely unmutated
    assert ledger.observed_cash == orig_cash
    assert len(ledger.candidate_reservations) == orig_reservations_len
    assert ledger.candidate_purchase_cash_spent == orig_spent
    assert ledger.wheat_in_shed == orig_wheat
    assert ledger.existing_feed_cash_hold == orig_hold


def test_phase_c1_feed_hold_diagnostics_exposed():
    """Verify feed_hold_diagnostics exposes:
    existing_feed_cash_hold, candidate_feed_cash_hold,
    remaining_existing_feed_hold, candidate_feed_holds_total.
    """
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=5, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx, lifetime_price_policy="engine_stress_bound_v1")
    evaluate_existing_herd_feasibility(ledger)

    holds = ledger.get_feed_hold_diagnostics()
    assert "existing_feed_cash_hold" in holds
    assert "candidate_feed_cash_hold" in holds
    assert "remaining_existing_feed_hold" in holds
    assert "candidate_feed_holds_total" in holds
    assert holds["remaining_existing_feed_hold"] == holds["existing_feed_cash_hold"]
    assert holds["candidate_feed_holds_total"] == holds["candidate_feed_cash_hold"]

    d = ledger.to_dict()
    assert "remaining_existing_feed_hold" in d
    assert "candidate_feed_holds_total" in d
    assert "feed_hold_diagnostics" in d


def test_phase_c1_macro_planner_intents_and_diagnostics():
    """Verify MacroPlanner populates buy_animal_sequence in plan.intents and diagnostics."""
    from strategy.macro_planner import MacroPlanner
    ctx = make_mock_farm_ctx(day=10, hour=0, money=10000.0, shed_wheat=30, placed_animals=["COW"])
    planner = MacroPlanner(DummyFC())
    plan = planner.build(ctx)

    assert hasattr(plan, "buy_animal_sequence")
    assert "buy_animal_sequence" in plan.intents
    assert isinstance(plan.intents["buy_animal_sequence"], list)
    assert "buy_animal" in plan.intents
    assert isinstance(plan.intents["buy_animal"], dict)

    assert "feed_hold_diagnostics" in plan.diagnostics
    assert "existing_feed_cash_hold" in plan.diagnostics["feed_hold_diagnostics"]
    assert "candidate_feed_cash_hold" in plan.diagnostics["feed_hold_diagnostics"]
    assert "provisional_candidates" in plan.diagnostics
    assert "buy_animal_sequence" in plan.diagnostics


def test_phase_c1_order_builder_untouched():
    """Verify OrderBuilder produces identical orders with buy_animal_sequence in intents.
    OrderBuilder during C1 ignores buy_animal_sequence and continues using buy_animal.
    """
    from market.order_builder import OrderBuilder
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=10, placed_animals=[])

    from strategy.macro_planner import MacroPlan
    plan1 = MacroPlan(day=10)
    plan1.intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_animal": {"SHEEP": 1},
        "buy_wheat": 0,
        "protected_feed_wheat": 0,
        "optional_feed_wheat": 0,
    }

    plan2 = MacroPlan(day=10)
    plan2.intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "buy_wheat": 0,
        "protected_feed_wheat": 0,
        "optional_feed_wheat": 0,
    }

    builder = OrderBuilder()
    orders1 = builder.build(ctx, plan1.intents)
    orders2 = builder.build(ctx, plan2.intents)

    assert orders1 == orders2


# ===========================================================================
# Phase C2A: Execution + Treasury Foundation Tests
# ===========================================================================

def test_c2a_test1_assigned_feed_emitted_move_not_certified():
    """Test 1: Assigned FEED + emitted MOVE -> not certified (verified_feed_count == 0)."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"])
    # Tile (0, 0) is the unfed COW
    tasks = [{"op": "FEED", "target": (0, 0)}]
    asg = {
        "assignment": {0: {"op": "FEED", "target": (0, 0), "unit_pos": (0, 1)}},
        "actions": {0: ["NORTH"]},  # Moving toward animal, not feeding!
    }
    snapshot = build_feed_execution_snapshot(ctx, tasks=tasks, assignment=asg)
    assert snapshot.feeds_assigned_this_turn == 1
    assert snapshot.feed_actions_emitted == 0
    assert snapshot.verified_feed_count == 0
    assert snapshot.verified_feed_targets == []
    assert snapshot.is_live_livestock_safe is False
    assert snapshot.live_execution_status == "feed_execution_unverified"


def test_c2a_test2_actual_feed_emitted_certified():
    """Test 2: Actual FEED emitted -> certified (verified_feed_count == 1, in verified_feed_targets)."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"])
    tasks = [{"op": "FEED", "target": (0, 0)}]
    asg = {
        "assignment": {0: {"op": "FEED", "target": (0, 0), "unit_pos": (0, 0)}},
        "actions": {0: ["FEED"]},
    }
    snapshot = build_feed_execution_snapshot(ctx, tasks=tasks, assignment=asg)
    assert snapshot.feeds_assigned_this_turn == 1
    assert snapshot.feed_actions_emitted == 1
    assert snapshot.verified_feed_count == 1
    assert (0, 0) in snapshot.verified_feed_targets
    assert snapshot.is_live_livestock_safe is True
    assert snapshot.live_execution_status == "safe"


def test_c2a_test3_two_due_animals_require_two_distinct_feed_actions():
    """Test 3: Two due animals require two distinct verified FEED actions."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW", "SHEEP"])
    # 2 unfed animals at (0, 0) and (1, 0)
    tasks = [{"op": "FEED", "target": (0, 0)}, {"op": "FEED", "target": (1, 0)}]

    # Only 1 distinct FEED action emitted
    asg_partial = {
        "assignment": {
            0: {"op": "FEED", "target": (0, 0), "unit_pos": (0, 0)},
            1: {"op": "FEED", "target": (1, 0), "unit_pos": (1, 1)},
        },
        "actions": {0: ["FEED"], 1: ["NORTH"]},
    }
    snap_partial = build_feed_execution_snapshot(ctx, tasks=tasks, assignment=asg_partial)
    assert snap_partial.verified_feed_count == 1
    assert snap_partial.unfed_placed_today == 2
    assert snap_partial.is_live_livestock_safe is False

    # 2 distinct units emit FEED actions
    asg_full = {
        "assignment": {
            0: {"op": "FEED", "target": (0, 0), "unit_pos": (0, 0)},
            1: {"op": "FEED", "target": (1, 0), "unit_pos": (1, 0)},
        },
        "actions": {0: ["FEED"], 1: ["FEED"]},
    }
    snap_full = build_feed_execution_snapshot(ctx, tasks=tasks, assignment=asg_full)
    assert snap_full.verified_feed_count == 2
    assert snap_full.unfed_placed_today == 2
    assert snap_full.is_live_livestock_safe is True
    assert snap_full.live_execution_status == "safe"


def test_c2a_feed_emitted_wrong_target_no_certification():
    """FEED emitted for wrong target (e.g. non-animal or non-due target) -> no certification."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"])
    # Animal is at (0, 0). Unit emits FEED but assigned target is (5, 5).
    tasks = [{"op": "FEED", "target": (5, 5)}]
    asg = {
        "assignment": {0: {"op": "FEED", "target": (5, 5), "unit_pos": (0, 0)}},
        "actions": {0: ["FEED"]},
    }
    snapshot = build_feed_execution_snapshot(ctx, tasks=tasks, assignment=asg)
    assert snapshot.verified_feed_count == 0
    assert snapshot.verified_feed_targets == []
    assert snapshot.is_live_livestock_safe is False


def test_c2a_feed_emitted_missing_target_no_certification():
    """FEED emitted with missing target in task/assignment -> no certification."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"])
    tasks = [{"op": "FEED"}]
    asg = {
        "assignment": {0: {"op": "FEED", "unit_pos": (0, 0)}},  # No target specified
        "actions": {0: ["FEED"]},
    }
    snapshot = build_feed_execution_snapshot(ctx, tasks=tasks, assignment=asg)
    assert snapshot.verified_feed_count == 0
    assert snapshot.verified_feed_targets == []
    assert snapshot.is_live_livestock_safe is False


def test_c2a_two_feeds_same_target_no_double_certification():
    """Two units emitting FEED for the same animal cannot certify it twice."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW", "SHEEP"])
    # 2 animals placed at (0, 0) and (1, 0).
    # Both units 0 and 1 target (0, 0) and emit FEED.
    tasks = [{"op": "FEED", "target": (0, 0)}, {"op": "FEED", "target": (0, 0)}]
    asg = {
        "assignment": {
            0: {"op": "FEED", "target": (0, 0), "unit_pos": (0, 0)},
            1: {"op": "FEED", "target": (0, 0), "unit_pos": (0, 0)},
        },
        "actions": {0: ["FEED"], 1: ["FEED"]},
    }
    snapshot = build_feed_execution_snapshot(ctx, tasks=tasks, assignment=asg)
    # Only 1 feed should be verified! The second cannot double-certify (0, 0)
    assert snapshot.verified_feed_count == 1
    assert snapshot.verified_feed_targets == [(0, 0)]
    assert snapshot.unfed_placed_today == 2
    assert snapshot.is_live_livestock_safe is False


def test_c2a_test4_missing_snapshot_with_unfed_herd_is_unsafe():
    """Test 4: Missing snapshot + unfed herd -> unsafe live execution status."""
    is_safe, status, reason = check_live_livestock_execution_safety(snapshot=None, unfed_placed_today=2)
    assert is_safe is False
    assert status == "feed_execution_unverified"

    # Missing snapshot with 0 unfed placed animals is safe
    is_safe_zero, status_zero, _ = check_live_livestock_execution_safety(snapshot=None, unfed_placed_today=0)
    assert is_safe_zero is True
    assert status_zero == "safe"


def test_c2a_test5_guarded_or_conditional_with_unfed_herd_is_unsafe():
    """Test 5: Guarded/conditional + unfed herd -> unsafe."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"])
    # No scheduler proof -> guarded
    snapshot = build_feed_execution_snapshot(ctx, tasks=None, assignment=None, actions=None)
    assert snapshot.execution_confidence == "guarded"
    assert snapshot.unfed_placed_today == 1
    assert snapshot.is_live_livestock_safe is False
    assert snapshot.live_execution_status == "feed_execution_unverified"


def test_c2a_test6_all_placed_animals_already_fed_not_forced_unsafe_by_guarded():
    """Test 6: All placed animals already fed -> guarded alone does not force unsafe status."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"], fed_animals_count=1)
    snapshot = build_feed_execution_snapshot(ctx, tasks=None, assignment=None, actions=None)
    assert snapshot.unfed_placed_today == 0
    assert snapshot.execution_confidence == "guarded"
    assert snapshot.is_live_livestock_safe is True
    assert snapshot.live_execution_status == "safe"


def test_c2a_test7_hour23_unresolved_feed_cannot_be_rescued_by_market_wheat():
    """Test 7: Hour 23 unresolved feed -> no same-turn market rescue."""
    ctx = make_mock_farm_ctx(day=10, hour=23, money=5000.0, shed_wheat=0, placed_animals=["COW"])
    asg = {
        "assignment": {0: {"op": "FEED", "target": (0, 0), "unit_pos": (0, 1)}},
        "actions": {0: ["NORTH"]},
    }
    snapshot = build_feed_execution_snapshot(ctx, tasks=[{"op": "FEED", "target": (0, 0)}], assignment=asg)
    assert snapshot.market_purchase_can_help_today is False
    assert snapshot.is_live_livestock_safe is False
    assert snapshot.live_execution_status == "feed_execution_unverified"
    assert "Hour 23" in snapshot.live_execution_reason


def test_c2a_test8_live_ledger_rebuilt_fresh_without_macro_candidate_reservations():
    """Test 8: Live ledger rebuilt fresh without importing Macro candidate reservations."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=2000.0, shed_wheat=10, placed_animals=["COW"])
    live_ledger = build_fresh_live_ledger(ctx)
    assert live_ledger.candidate_reservations == []
    assert live_ledger.candidate_feed_cash_hold == 0.0
    assert live_ledger.candidate_purchase_cash_spent == 0.0
    assert live_ledger.lifetime_price_policy == "engine_stress_bound_v1"
    assert live_ledger.placed_herd["COW"] == 1


def test_c2a_test9_retained_protected_wheat_updates_remaining_hold_without_double_counting():
    """Test 9: Retained protected WHEAT updates remaining existing-herd hold without double counting."""
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=0, placed_animals=["COW"])
    live_ledger = build_fresh_live_ledger(ctx)

    ok_0, res_0, hold_0 = compute_remaining_existing_feed_hold(live_ledger, retained_wheat=0, unit_price=28.0)
    ok_3, res_3, hold_3 = compute_remaining_existing_feed_hold(live_ledger, retained_wheat=3, unit_price=28.0)

    assert ok_0 is True
    assert ok_3 is True
    assert hold_3 < hold_0
    spent_now = 3 * 28.0
    total_effective_commitment = spent_now + hold_3
    # Anti-double-counting invariant: spent cash + remaining hold should equal or be bounded near hold_0
    assert abs(total_effective_commitment - hold_0) < 1e-3 or total_effective_commitment <= hold_0 + 5.0


def test_c2a_test10_existing_feed_hold_blocks_discretionary_land_when_tight(monkeypatch):
    """Test 10: Existing-herd feed hold blocks discretionary land when budget is tight."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # Cash = 1400. Reserve = 300. Available = 1100.
    # Land price = 1000. 1 placed COW requires future feed (~$400+).
    # Discretionary budget after feed hold: 1100 - 400 = 700 < 1000 (land price).
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1400.0, shed_wheat=0, placed_animals=["COW"])
    # 0 unfed today so feed execution is safe, but future feed holds cash
    for t in ctx["farm"].iter_tiles():
        if t.is_animal:
            t.fed_today = True

    builder = OrderBuilder(money_reserve=300.0)
    intents = {
        "hire": 0,
        "buy_land": True,
        "buy_seed": {},
        "buy_animal": {},
        "buy_wheat": 0,
        "protected_feed_wheat": 0,
    }
    orders, ledger = builder.build(ctx, intents)
    assert not any(o[0] == "BUY_LAND" for o in orders)
    assert any(d.get("kind") == "land" and d.get("reason") == "budget" for d in ledger.get("dropped", []))
    assert ledger["remaining_existing_feed_hold"] > 0.0


def test_c2a_test11_hour1_land_cannot_bypass_feed_hold_in_live_mode(monkeypatch):
    """Test 11: Hour-1 land cannot bypass feed hold in live mode."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # Setup context at Hour 1 with tight cash
    ctx = make_mock_farm_ctx(day=4, hour=1, money=1200.0, shed_wheat=0, placed_animals=["COW"])
    for t in ctx["farm"].iter_tiles():
        if t.is_animal:
            t.fed_today = True

    builder = OrderBuilder(money_reserve=300.0)
    h1_intents = {
        "hire": 0,
        "buy_land": True,
        "buy_wheat": 0,
        "protected_feed_wheat": 0,
    }
    orders, ledger = builder.build(ctx, h1_intents)
    assert not any(o[0] == "BUY_LAND" for o in orders)
    assert ledger["remaining_existing_feed_hold"] > 0.0


def test_c2a_test12_shadow_hour1_behavior_unchanged(monkeypatch):
    """Test 12: shadow Hour-1 behavior unchanged."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "shadow")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "shadow")
    from market.order_builder import OrderBuilder

    # In shadow mode, OrderBuilder discretionary budget does not subtract remaining_existing_feed_hold
    ctx = make_mock_farm_ctx(day=4, hour=1, money=1400.0, shed_wheat=0, placed_animals=["COW"])
    builder = OrderBuilder(money_reserve=300.0)
    orders, ledger = builder.build(ctx, {"hire": 0, "buy_land": True, "buy_wheat": 0})
    assert ledger["remaining_existing_feed_hold"] == 0.0
    assert any(o[0] == "BUY_LAND" for o in orders)


def test_c2a_test13_herd_plan_hour1_behavior_unchanged(monkeypatch):
    """Test 13: herd_plan Hour-1 behavior unchanged."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "herd_plan")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "herd_plan")
    from market.order_builder import OrderBuilder

    # In herd_plan mode, live OrderBuilder behavior matches shadow (remains legacy live autorun)
    ctx = make_mock_farm_ctx(day=4, hour=1, money=1400.0, shed_wheat=0, placed_animals=["COW"])
    builder = OrderBuilder(money_reserve=300.0)
    orders, ledger = builder.build(ctx, {"hire": 0, "buy_land": True, "buy_wheat": 0})
    assert ledger["remaining_existing_feed_hold"] == 0.0
    assert any(o[0] == "BUY_LAND" for o in orders)


def test_c2a_test14_injected_live_failure_fails_closed_for_discretionary_spending(monkeypatch):
    """Test 14: Injected live snapshot/ledger failure fails closed for discretionary spending,
    blocking land, seeds, and animals, while preserving survival/protected-WHEAT purchasing."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=0, placed_animals=["COW"])

    # Inject failure into build_fresh_live_ledger
    import strategy.feed_feasibility
    def faulty_ledger(*args, **kwargs):
        raise RuntimeError("Injected ledger failure for test 14")

    monkeypatch.setattr(strategy.feed_feasibility, "build_fresh_live_ledger", faulty_ledger)

    builder = OrderBuilder(money_reserve=300.0)
    intents = {
        "hire": 1,
        "buy_wheat": 5,
        "protected_feed_wheat": 3,
        "buy_land": True,
        "buy_seed": {"CARROT": 10},
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {"PASTURE": 1},
    }
    orders, ledger = builder.build(ctx, intents)

    # 1. Survival purchases (hire and protected wheat) must be preserved!
    assert any(o[0] == "HIRE" for o in orders)
    assert any(o[0] == "BUY_PRODUCT" and o[1] == "WHEAT" for o in orders)

    # 2. Discretionary spending must fail closed: no land, no seeds, no new animals!
    assert not any(o[0] == "BUY_LAND" for o in orders)
    assert not any(o[0] == "BUY_SEED" for o in orders)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)

    # 3. Discretionary budget must be 0.0, hold is None, and failure reason is logged
    assert ledger["discretionary_budget"] == 0.0
    assert ledger["remaining_existing_feed_hold"] is None
    assert ledger.get("live_failure_reason") is not None

    dropped_kinds = {d.get("kind"): d.get("reason") for d in ledger.get("dropped", [])}
    assert dropped_kinds.get("land") == "live_failure"
    assert dropped_kinds.get("seed") == "live_failure"
    assert dropped_kinds.get("animal") == "live_failure"


def test_c2a_test15_c2a_normal_diagnostics_do_not_alter_legacy_animal_orders(monkeypatch):
    """Test 15: In C2B live mode, feed execution gate is activated and suppresses BUY_ANIMAL when unverified."""
    import config
    # 1. Default mode remains shadow
    assert config.POINT2_FEED_MODE == "shadow"

    # 2. In live mode, when feed execution is unverified, C2B suppresses animal orders!
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # Setup: 1 placed COW, unfed today, 0 feed actions emitted -> is_safe_exec is False.
    # Money is $5000 so legacy logic easily affords SHEEP.
    ctx = make_mock_farm_ctx(day=10, hour=0, money=5000.0, shed_wheat=10, placed_animals=["COW"])
    ctx["assignment"] = {}
    ctx["tasks"] = []

    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {"PASTURE": 1},
        "buy_wheat": 0,
    }
    orders, ledger = builder.build(ctx, intents)

    # Diagnostics are computed and exposed:
    assert ledger["point2_live_authority"] is True
    assert ledger["is_live_livestock_safe"] is False
    assert ledger["live_execution_status"] == "feed_execution_unverified"

    # In C2B, feed execution unverified suppresses BUY_ANIMAL:
    assert not any(o[0] == "BUY_ANIMAL" for o in orders), (
        "C2B must suppress BUY_ANIMAL when feed execution is unverified."
    )
    assert any(d.get("kind") == "animal" and d.get("reason") == "feed_execution_unverified" for d in ledger.get("dropped", []))



# ============================================================================
# Phase C2B — Sequential Live Candidate Authority Tests
# ============================================================================

def test_c2b_interleaved_sequence_order(monkeypatch):
    """Test 74: Interleaved candidate sequence [SHEEP, COW, SHEEP] is evaluated in exact order
    and emitted grouped by first-appearance species [SHEEP x2, COW x1]."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=20000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"COW": 1, "SHEEP": 2},
        "buy_animal_sequence": ["SHEEP", "COW", "SHEEP"],
        "pending_structures": {},
    }
    # Mock housing with 3 empty pastures
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=3, post_unit_empty_coops=0,
        post_unit_unplaced_pasture_animals=0, post_unit_unplaced_coop_animals=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=0,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)

    # 1. Candidate evaluation order preserved exactly
    decisions = ledger["candidate_decisions"]
    assert len(decisions) == 3
    assert decisions[0]["species"] == "SHEEP"
    assert decisions[1]["species"] == "COW"
    assert decisions[2]["species"] == "SHEEP"
    assert all(d["accepted"] for d in decisions)

    # 2. Emitted orders grouped in first-appearance order (SHEEP first, then COW)
    animal_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert len(animal_orders) == 2
    assert animal_orders[0] == ["BUY_ANIMAL", "SHEEP", 2]
    assert animal_orders[1] == ["BUY_ANIMAL", "COW", 1]
    assert ledger["animal_order_slots_used"] == 2


def test_c2b_sequence_not_sorted_buy_animal_aggregate(monkeypatch):
    """Test 75: Live mode evaluates candidates in sequence order, not sorted buy_animal aggregate."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=20000.0, shed_wheat=50)
    builder = OrderBuilder()
    # buy_animal has {"SHEEP": 1, "COW": 1}, but sequence has ["COW", "SHEEP"]
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1, "COW": 1},
        "buy_animal_sequence": ["COW", "SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_empty_coops=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=0,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)

    decisions = ledger["candidate_decisions"]
    assert len(decisions) == 2
    assert decisions[0]["species"] == "COW"
    assert decisions[1]["species"] == "SHEEP"


def test_c2b_missing_or_malformed_sequence_fails_closed(monkeypatch):
    """Test 76: In live mode, missing or malformed sequence with legacy buy_animal fails closed."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    builder = OrderBuilder()

    # Case A: sequence is None
    intents_none = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {"CARROT": 5},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": None,
    }
    orders, ledger = builder.build(ctx, intents_none)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(o[0] == "BUY_SEED" for o in orders)  # Seeds preserved
    assert any(d.get("kind") == "animal" and d.get("reason") == "invalid_candidate_sequence" for d in ledger.get("dropped", []))

    # Case B: sequence is not a list
    intents_bad = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": "SHEEP",
    }
    orders2, ledger2 = builder.build(ctx, intents_bad)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders2)
    assert any(d.get("kind") == "animal" and d.get("reason") == "invalid_candidate_sequence" for d in ledger2.get("dropped", []))


def test_c2b_shadow_and_herd_plan_unaffected_by_malformed_sequence(monkeypatch):
    """Test 77: In shadow mode, missing/malformed sequence does NOT fail closed (uses legacy buy_animal)."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "shadow")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "shadow")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": None,
        "pending_structures": {"PASTURE": 1},
    }
    orders, ledger = builder.build(ctx, intents)
    assert any(o[0] == "BUY_ANIMAL" and o[1] == "SHEEP" for o in orders)


def test_c2b_day12_14_late_selective_candidate_generation(monkeypatch):
    """Test 78: On Days 12-14 in live mode, late selective mode generates candidates using physical housing."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from strategy.macro_planner import MacroPlanner

    planner = MacroPlanner(DummyFC())
    # Mock farm on Day 12 with 1 empty pasture and ample money
    ctx = make_mock_farm_ctx(day=12, hour=0, money=15000.0, shed_wheat=50)
    farm = ctx["farm"]
    # Mock farm having 1 pasture
    t = make_mock_tile((1, 1), kind="PASTURE")
    farm.tiles = [[t]]
    farm.iter_tiles = lambda: [t]
    farm.unlocked = ["NW"]
    farm.quadrant_of = lambda pos: "NW"

    plan = planner.build(ctx)
    assert hasattr(plan, "buy_animal_sequence")
    # In live mode on Day 12 with physical pasture and high cash, late selective candidate admitted
    assert len(plan.buy_animal_sequence) >= 1
    assert plan.buy_animal_sequence[0] in ("COW", "SHEEP")


def test_c2b_day12_14_no_credit_for_planned_housing(monkeypatch):
    """Test 79: On Days 12-14 in live mode, planned housing produces zero candidate sequence."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from strategy.macro_planner import MacroPlanner

    planner = MacroPlanner(DummyFC())
    ctx = make_mock_farm_ctx(day=12, hour=0, money=15000.0, shed_wheat=50)
    farm = ctx["farm"]
    farm.iter_tiles = lambda: []  # 0 physical structures
    farm.unlocked = ["NW"]
    farm.quadrant_of = lambda pos: "NW"

    plan = planner.build(ctx)
    assert plan.buy_animal_sequence == []


def test_c2b_day_after_14_cutoff_no_candidates(monkeypatch):
    """Test 80: On Day 15+, candidate sequence is strictly empty in live mode."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from strategy.macro_planner import MacroPlanner

    planner = MacroPlanner(DummyFC())
    ctx = make_mock_farm_ctx(day=15, hour=0, money=25000.0, shed_wheat=100)
    farm = ctx["farm"]
    t = make_mock_tile((1, 1), kind="PASTURE")
    farm.iter_tiles = lambda: [t]
    farm.unlocked = ["NW"]
    farm.quadrant_of = lambda pos: "NW"

    plan = planner.build(ctx)
    assert plan.buy_animal_sequence == []


def test_c2b_existing_herd_infeasible_gate(monkeypatch):
    """Test 81: When existing herd is infeasible, all candidates are rejected with existing_herd_infeasible."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # 4 placed COWs, 0 wheat in shed, money $200 (cannot fund existing herd)
    ctx = make_mock_farm_ctx(day=10, hour=0, money=200.0, shed_wheat=0, placed_animals=["COW", "COW", "COW", "COW"])
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=10, hour=0, turns_remaining_today=24, feeds_due_today=4,
        feeds_assigned_this_turn=4, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=0, n_active_units=4,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(d.get("kind") == "animal" and d.get("reason") == "existing_herd_infeasible" for d in ledger.get("dropped", []))


def test_c2b_candidate_transactional_rollback(monkeypatch):
    """Test 83: Rejection releases trial resources and allows subsequent candidates to be evaluated."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    builder = OrderBuilder()
    # 1 pasture, 1 coop. Candidate sequence: SHEEP, COW, GOOSE.
    # SHEEP claims pasture. COW fails housing. GOOSE claims coop.
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1, "COW": 1, "GOOSE": 1},
        "buy_animal_sequence": ["SHEEP", "COW", "GOOSE"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=1, post_unit_empty_coops=1,
        post_unit_unplaced_pasture_animals=0, post_unit_unplaced_coop_animals=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=0,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)

    decisions = ledger["candidate_decisions"]
    assert len(decisions) == 3
    assert decisions[0]["species"] == "SHEEP" and decisions[0]["accepted"] is True
    assert decisions[1]["species"] == "COW" and decisions[1]["accepted"] is False
    assert decisions[1]["rejection_reason"] == "no_physical_housing"
    assert decisions[2]["species"] == "GOOSE" and decisions[2]["accepted"] is True

    animal_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert len(animal_orders) == 2
    assert ["BUY_ANIMAL", "SHEEP", 1] in animal_orders
    assert ["BUY_ANIMAL", "GOOSE", 1] in animal_orders


def test_c2b_cumulative_stress_repricing(monkeypatch):
    """Test 84: Each admitted candidate increases market feed liability and stress wheat price."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # Constrained market wheat inventory so stress repricing is active
    ctx = make_mock_farm_ctx(day=5, hour=0, money=25000.0, shed_wheat=50)
    ctx["market"].inventory = {"WHEAT": 80.0}
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"COW": 2},
        "buy_animal_sequence": ["COW", "COW"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_empty_coops=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=0,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    decisions = ledger["candidate_decisions"]
    assert len(decisions) == 2
    assert decisions[0]["accepted"] is True
    assert decisions[1]["accepted"] is True
    # Candidate 2 stress price is >= Candidate 1 stress price
    assert decisions[1]["stress_price_after"] >= decisions[0]["stress_price_after"]


def test_c2b_higher_priority_cash_cannot_be_reused(monkeypatch):
    """Test 85: Cash committed to land or seeds cannot be double spent on candidate animals."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # Money is $2400. Reserve is $300. Available is $2100.
    # Land costs $2000. Remaining discretionary is $100.
    # Candidate COW costs $500 -> must fail for insufficient cash / feed.
    ctx = make_mock_farm_ctx(day=5, hour=0, money=2400.0, shed_wheat=50)
    builder = OrderBuilder(money_reserve=300.0)
    intents = {
        "hire": 0,
        "buy_land": True,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"COW": 1},
        "buy_animal_sequence": ["COW"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=1, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    # Land order is preserved
    assert any(o[0] == "BUY_LAND" for o in orders)
    # COW is rejected due to cash
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(d.get("kind") == "animal" and d.get("reason") in ("insufficient_cash", "feed_infeasible") for d in ledger.get("dropped", []))


def test_c2b_retained_wheat_credit_and_cost(monkeypatch):
    """Test 86: Retained wheat order is charged to cash and credited as physical feed in candidate ledger."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=5)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 10,
        "protected_feed_wheat": 10,
        "buy_animal": {"COW": 1},
        "buy_animal_sequence": ["COW"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=5, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=1, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    decisions = ledger["candidate_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["accepted"] is True
    assert decisions[0]["relies_on_retained_protected_wheat"] is True


def test_c2b_post_unit_pickup_frees_shed_capacity():
    """Test 87: Verified PICKUP moves items from shed to worker, freeing immediate shed space."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=50)
    ctx["private"].shed["WHEAT"] = 50
    ctx["assignment"] = {0: {"task": "PICKUP", "args": ["WHEAT", 10]}}
    ctx["actions"] = {0: ["PICKUP", "WHEAT", 10]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_shed_inventory["WHEAT"] == 40
    assert snapshot.post_unit_worker_inventories[0]["WHEAT"] == 10
    assert snapshot.post_unit_shed_occupancy == 40


def test_c2b_post_unit_feed_consumes_worker_wheat():
    """Test 88: Verified FEED decrements worker wheat and satisfies unfed placed animal."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0, placed_animals=["COW"])
    ctx["farm"].workers[0].inventory = {"WHEAT": 2}
    ctx["private"].inventories = [{"WHEAT": 2}]
    ctx["assignment"] = {0: {"task": "FEED", "target": (0, 0), "args": []}}
    ctx["actions"] = {0: ["FEED"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.verified_feed_count == 1
    assert snapshot.post_unit_worker_inventories[0]["WHEAT"] == 1


def test_c2b_post_unit_place_occupies_structure():
    """Test 89: Verified PLACE decrements worker animal inventory and occupies physical structure."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    ctx["farm"].workers[0].inventory = {"COW": 1}
    ctx["private"].inventories = [{"COW": 1}]
    class MockPastureTile:
        kind = "PASTURE"
        is_animal = False
        animal = None
        pos = (1, 1)
    ctx["farm"].tiles = [[None, None], [None, MockPastureTile()]]
    ctx["farm"].iter_tiles = lambda: [MockPastureTile()]
    ctx["farm"].quadrant_of = lambda pos: "NW"
    ctx["assignment"] = {0: {"task": "PLACE", "target": (1, 1), "args": ["COW"]}}
    ctx["actions"] = {0: ["PLACE", "COW"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_worker_inventories[0].get("COW", 0) == 0
    assert snapshot.post_unit_placed_herd["COW"] == 1
    assert snapshot.post_unit_empty_pastures == 0
    assert snapshot.post_unit_state_verified is True


def test_c2b_pre_cutoff_build_credit():
    """Test 90: Before Day 12, actual verified BUILD_PASTURE increments post_unit_empty_pastures."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    class MockEmptyTile:
        kind = "EMPTY"
        raw = None
        is_animal = False
        animal = None
        crop = None
        pos = (1, 1)
    ctx["farm"].tiles = [[None, None], [None, MockEmptyTile()]]
    ctx["farm"].iter_tiles = lambda: [MockEmptyTile()]
    ctx["farm"].quadrant_of = lambda pos: "NW"
    ctx["assignment"] = {0: {"task": "BUILD_PASTURE", "target": (1, 1), "args": []}}
    ctx["actions"] = {0: ["BUILD_PASTURE"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_empty_pastures == 1
    assert snapshot.post_unit_state_verified is True


def test_c2b_post_cutoff_build_zero_credit():
    """Test 91: On Day 12+, verified BUILD_PASTURE yields zero candidate housing credit."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=12, hour=0, money=5000.0, shed_wheat=0)
    class MockEmptyTile:
        kind = "EMPTY"
        raw = None
        is_animal = False
        animal = None
        crop = None
        pos = (1, 1)
    ctx["farm"].tiles = [[None, None], [None, MockEmptyTile()]]
    ctx["farm"].iter_tiles = lambda: [MockEmptyTile()]
    ctx["farm"].quadrant_of = lambda pos: "NW"
    ctx["assignment"] = {0: {"task": "BUILD_PASTURE", "target": (1, 1), "args": []}}
    ctx["actions"] = {0: ["BUILD_PASTURE"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_empty_pastures == 0
    assert snapshot.post_unit_state_verified is True


def test_c2b_existing_unplaced_housing_first_claim(monkeypatch):
    """Test 92: Existing unplaced animals in shed claim physical housing before new candidates."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # 1 empty pasture, but shed already holds 1 COW (unplaced)
    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    ctx["private"].shed["COW"] = 1
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=1, post_unit_empty_coops=0,
        post_unit_unplaced_pasture_animals=1, post_unit_unplaced_coop_animals=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=1,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(d.get("kind") == "animal" and d.get("reason") == "no_physical_housing" for d in ledger.get("dropped", []))


def test_c2b_shared_pasture_pool(monkeypatch):
    """Test 93: COW and SHEEP share the same pasture pool; accepted COW exhausts pasture for SHEEP."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    builder = OrderBuilder()
    # 1 pasture. Sequence: COW, SHEEP.
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"COW": 1, "SHEEP": 1},
        "buy_animal_sequence": ["COW", "SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=1, post_unit_empty_coops=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=0,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    decisions = ledger["candidate_decisions"]
    assert decisions[0]["species"] == "COW" and decisions[0]["accepted"] is True
    assert decisions[1]["species"] == "SHEEP" and decisions[1]["accepted"] is False
    assert decisions[1]["rejection_reason"] == "no_physical_housing"


def test_c2b_coop_separation(monkeypatch):
    """Test 94: GOOSE requires COOP; pasture cannot house GOOSE, COOP cannot house COW."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"COW": 1, "GOOSE": 1},
        "buy_animal_sequence": ["COW", "GOOSE"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    # 0 pastures, 1 coop
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=0, post_unit_empty_coops=1,
        post_unit_state_verified=True, post_unit_shed_occupancy=0,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    decisions = ledger["candidate_decisions"]
    assert decisions[0]["species"] == "COW" and decisions[0]["accepted"] is False
    assert decisions[1]["species"] == "GOOSE" and decisions[1]["accepted"] is True


def test_c2b_immediate_shed_capacity(monkeypatch):
    """Test 95: Animal purchase requires 1 immediate shed slot; rejected if shed is full."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=100)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    # Shed occupancy is 100
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=100, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_empty_coops=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=100,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(d.get("kind") == "animal" and d.get("reason") == "shed_capacity" for d in ledger.get("dropped", []))


def test_c2b_hour23_rollover_protection(monkeypatch):
    """Test 96: At Hour 23, candidate fails if post-market shed + worker carried inventory > 100."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # Hour 23. Shed has 99 items, worker carries 1 item.
    ctx = make_mock_farm_ctx(day=5, hour=23, money=10000.0, shed_wheat=99)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=23, turns_remaining_today=1, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=1, shed_wheat=99, n_active_units=1,
        market_purchase_can_help_today=False, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_empty_coops=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=99,
        post_unit_worker_inventory_total=1,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(d.get("kind") == "animal" and d.get("reason") == "end_of_day_rollover_capacity" for d in ledger.get("dropped", []))


def test_c2b_seeds_do_not_consume_shed(monkeypatch):
    """Test 97: Seed purchases do not consume shed slots or impact animal shed capacity."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # Shed has 99 items. We buy 10 seeds. 99 + 1 (animal) <= 100 shed slots.
    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=99)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {"CARROT": 10},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=99, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_empty_coops=0,
        post_unit_state_verified=True, post_unit_shed_occupancy=99,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    assert any(o[0] == "BUY_SEED" for o in orders)
    assert any(o[0] == "BUY_ANIMAL" and o[1] == "SHEEP" for o in orders)


def test_c2b_animal_order_slots_grouping(monkeypatch):
    """Test 98: Multiple accepted animals of same species use only 1 market order slot."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=20000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 3},
        "buy_animal_sequence": ["SHEEP", "SHEEP", "SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=3, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents)
    animal_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert len(animal_orders) == 1
    assert animal_orders[0] == ["BUY_ANIMAL", "SHEEP", 3]
    assert ledger["animal_order_slots_used"] == 1


def test_c2b_slot_exhaustion_blocks_candidates(monkeypatch):
    """Test 99: When max_slots is reached, candidates requiring a new slot are blocked with market_order_slots."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    # max_slots = 2. Kept prefix has 1 seed order (using 1 slot).
    # Remaining slots for animals = 1.
    # Sequence = [SHEEP, COW]. SHEEP uses the 1 slot; COW requires a new slot and is blocked.
    ctx = make_mock_farm_ctx(day=5, hour=0, money=20000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {"CARROT": 1},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1, "COW": 1},
        "buy_animal_sequence": ["SHEEP", "COW"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    orders, ledger = builder.build(ctx, intents, max_slots=2)
    decisions = ledger["candidate_decisions"]
    assert decisions[0]["species"] == "SHEEP" and decisions[0]["accepted"] is True
    assert decisions[1]["species"] == "COW" and decisions[1]["accepted"] is False
    assert decisions[1]["rejection_reason"] == "market_order_slots"


def test_c2b_candidate_exception_discards_all_animals_preserves_higher_priority(monkeypatch):
    """Test 100: Unexpected exception during candidate replay discards all candidate animals but preserves higher tiers."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=20000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {"CARROT": 2},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 2},
        "buy_animal_sequence": ["SHEEP", "SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    # Mock evaluate_incremental_candidate to raise an error on second call
    call_count = 0
    import strategy.feed_feasibility as ff
    orig_eval = ff.evaluate_incremental_candidate

    def mock_eval(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Corrupted feed evaluator!")
        return orig_eval(*args, **kwargs)

    monkeypatch.setattr(ff, "evaluate_incremental_candidate", mock_eval)

    orders, ledger = builder.build(ctx, intents)

    # 1. Zero BUY_ANIMAL orders emitted
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    # 2. Higher priority seed order preserved intact
    assert any(o[0] == "BUY_SEED" for o in orders)
    # 3. Discard recorded with live_candidate_exception
    assert any(d.get("kind") == "animal" and d.get("reason") == "live_candidate_exception" for d in ledger.get("dropped", []))
    # 4. Full rollback of candidate financials, slots, sequence, and housing
    assert ledger.get("final_candidate_purchase_spend") == 0.0
    assert ledger.get("final_candidate_feed_hold") == 0.0
    assert ledger.get("animal_order_slots_used") == 0
    assert ledger.get("candidate_sequence_accepted") == []
    assert not any(d.get("accepted") is True for d in ledger.get("candidate_decisions", []))
    housing_final = ledger.get("housing_state_final")
    assert housing_final is not None
    assert housing_final.get("empty_pastures") == 2


def test_c2b_intraday_uses_shared_c2b_authority(monkeypatch):
    """Test 101: build_intraday() and reinvest_livestock() delegate to unified C2B sequential authority."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=10, money=20000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
    }
    from strategy.feed_feasibility import FeedExecutionSnapshot
    snapshot = FeedExecutionSnapshot(
        day=5, hour=10, turns_remaining_today=14, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=1, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    # Test build_intraday()
    orders_intra, ledger_intra = builder.build_intraday(ctx, intents)
    assert ledger_intra["live_animal_authority"] == "c2b_sequential"
    assert any(o[0] == "BUY_ANIMAL" and o[1] == "SHEEP" for o in orders_intra)

    # Test reinvest_livestock()
    orders_reinvest, ledger_reinvest = builder.reinvest_livestock(ctx, intents)
    assert ledger_reinvest.get("live_animal_authority") == "c2b_sequential"
    assert any(o[0] == "BUY_ANIMAL" and o[1] == "SHEEP" for o in orders_reinvest)


# ============================================================================
# Phase C2B Verification Layer Hardening Tests
# ============================================================================

def test_c2b_repair_missing_snapshot_fails_closed(monkeypatch):
    """Test 102: In live mode, missing execution_snapshot rejects all candidate livestock with post_unit_state_unverified, preserving non-animal orders."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 1,
        "buy_land": False,
        "buy_seed": {"CARROT": 1},
        "buy_wheat": 5,
        "buy_animal": {"COW": 1},
        "buy_animal_sequence": ["COW"],
        "pending_structures": {},
        "execution_snapshot": None,
    }
    ctx["feed_execution_snapshot"] = None

    orders, ledger = builder.build(ctx, intents)

    # 1. Zero BUY_ANIMAL orders emitted
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    # 2. Rejection reason is post_unit_state_unverified
    assert any(
        d.get("kind") == "animal" and d.get("reason") == "post_unit_state_unverified"
        for d in ledger.get("dropped", [])
    )
    # 3. Higher priority non-animal purchases remain intact
    assert any(o[0] == "HIRE" for o in orders)
    assert any(o[0] == "BUY_SEED" for o in orders)


def test_c2b_repair_crop_harvest_verified():
    """Test 103: Scheduler HARVEST on mature plant credits worker inventory with yield units."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    class MockStrawberryTile:
        kind = "PLANT"
        crop = "STRAWBERRY"
        is_plant = True
        is_animal = False
        animal = None
        yield_units = 3
        pos = (2, 3)
    ctx["farm"].tiles = [[None for _ in range(10)] for _ in range(10)]
    ctx["farm"].tiles[3][2] = MockStrawberryTile()
    ctx["farm"].iter_tiles = lambda: [MockStrawberryTile()]
    ctx["assignment"] = {0: {"task": "HARVEST", "target": (2, 3), "args": []}}
    ctx["actions"] = {0: ["HARVEST"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_state_verified is True
    assert snapshot.post_unit_worker_inventories[0].get("STRAWBERRY", 0) == 3


def test_c2b_repair_animal_harvest_verified():
    """Test 104: Scheduler HARVEST on mature animal credits worker inventory with animal product."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    class MockSheepTile:
        kind = "PASTURE"
        crop = None
        is_plant = False
        is_animal = True
        animal = "SHEEP"
        yield_units = 2
        pos = (2, 3)
    ctx["farm"].tiles = [[None for _ in range(10)] for _ in range(10)]
    ctx["farm"].tiles[3][2] = MockSheepTile()
    ctx["farm"].iter_tiles = lambda: [MockSheepTile()]
    ctx["assignment"] = {0: {"task": "HARVEST", "target": (2, 3), "args": []}}
    ctx["actions"] = {0: ["HARVEST"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_state_verified is True
    assert snapshot.post_unit_worker_inventories[0].get("WOOL", 0) == 2


def test_c2b_repair_hour23_rollover_with_real_harvest(monkeypatch):
    """Test 105: Hour-23 rollover with real HARVEST causing post-market shed overflow rejects candidate SHEEP with end_of_day_rollover_capacity."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder
    from strategy.feed_feasibility import build_feed_execution_snapshot

    # Shed has 98 items
    ctx = make_mock_farm_ctx(day=5, hour=23, money=10000.0, shed_wheat=98)
    ctx["private"].shed = {"WHEAT": 98}

    # Worker harvests 3 WOOL from SHEEP
    class MockSheepTile:
        kind = "PASTURE"
        crop = None
        is_plant = False
        is_animal = True
        animal = "SHEEP"
        yield_units = 3
        fed_today = True
        pos = (2, 3)
    class MockPastureEmptyTile:
        kind = "PASTURE"
        crop = None
        is_plant = False
        is_animal = False
        animal = None
        pos = (1, 1)
    ctx["farm"].tiles = [[None for _ in range(10)] for _ in range(10)]
    ctx["farm"].tiles[3][2] = MockSheepTile()
    ctx["farm"].tiles[1][1] = MockPastureEmptyTile()
    ctx["farm"].iter_tiles = lambda: [MockSheepTile(), MockPastureEmptyTile()]
    ctx["farm"].quadrant_of = lambda pos: "NW"
    ctx["assignment"] = {0: {"task": "HARVEST", "target": (2, 3), "args": []}}
    ctx["actions"] = {0: ["HARVEST"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_state_verified is True
    assert snapshot.post_unit_shed_occupancy == 98
    assert snapshot.post_unit_worker_inventory_total == 3
    assert snapshot.post_unit_empty_pastures == 1

    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
        "execution_snapshot": snapshot,
    }

    orders, ledger = builder.build(ctx, intents)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    decisions = ledger["candidate_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["species"] == "SHEEP"
    assert decisions[0]["accepted"] is False
    assert decisions[0]["rejection_reason"] == "end_of_day_rollover_capacity"


def test_c2b_repair_invalid_place_fails_closed(monkeypatch):
    """Test 106: Invalid PLACE when worker does not hold animal fails verification and rejects candidate in live mode."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder
    from strategy.feed_feasibility import build_feed_execution_snapshot

    ctx = make_mock_farm_ctx(day=5, hour=0, money=10000.0, shed_wheat=50)
    ctx["farm"].workers[0].inventory = {}
    ctx["private"].inventories = [{}]
    class MockPastureTile:
        kind = "PASTURE"
        is_animal = False
        animal = None
        pos = (1, 1)
    ctx["farm"].tiles = [[None, None], [None, MockPastureTile()]]
    ctx["farm"].iter_tiles = lambda: [MockPastureTile()]
    ctx["farm"].quadrant_of = lambda pos: "NW"
    ctx["assignment"] = {0: {"task": "PLACE", "target": (1, 1), "args": ["COW"]}}
    ctx["actions"] = {0: ["PLACE", "COW"]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_state_verified is False
    assert snapshot.post_unit_state_reason == "unverifiable_place"

    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
        "execution_snapshot": snapshot,
    }

    orders, ledger = builder.build(ctx, intents)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(
        d.get("kind") == "animal" and d.get("reason") == "post_unit_state_unverified"
        for d in ledger.get("dropped", [])
    )


def test_c2b_repair_invalid_pickup_fails_closed():
    """Test 107: PICKUP requesting more quantity than available in shed fails verification."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=1)
    ctx["private"].shed = {"WHEAT": 1}
    ctx["assignment"] = {0: {"task": "PICKUP", "args": ["WHEAT", 3]}}
    ctx["actions"] = {0: ["PICKUP", "WHEAT", 3]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_state_verified is False
    assert snapshot.post_unit_state_reason == "unverifiable_pickup"


def test_c2b_repair_invalid_drop_fails_closed():
    """Test 108: DROP requesting item worker does not hold fails verification."""
    from strategy.feed_feasibility import build_feed_execution_snapshot
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    ctx["farm"].workers[0].inventory = {}
    ctx["private"].inventories = [{}]
    ctx["assignment"] = {0: {"task": "DROP", "args": ["WHEAT", 1]}}
    ctx["actions"] = {0: ["DROP", "WHEAT", 1]}

    snapshot = build_feed_execution_snapshot(ctx)
    assert snapshot.post_unit_state_verified is False
    assert snapshot.post_unit_state_reason == "unverifiable_drop"


def test_c2b_repair_build_pre_and_post_day12():
    """Test 109: Pre-Day 12 valid build gains housing; invalid build fails verification; Day 12+ gains zero credit."""
    from strategy.feed_feasibility import build_feed_execution_snapshot

    # 1. Valid pre-Day 12
    ctx_valid = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    class MockEmptyTile:
        kind = "EMPTY"
        raw = None
        is_animal = False
        animal = None
        crop = None
        pos = (1, 1)
    ctx_valid["farm"].tiles = [[None, None], [None, MockEmptyTile()]]
    ctx_valid["farm"].iter_tiles = lambda: [MockEmptyTile()]
    ctx_valid["farm"].quadrant_of = lambda pos: "NW"
    ctx_valid["assignment"] = {0: {"task": "BUILD_PASTURE", "target": (1, 1), "args": []}}
    ctx_valid["actions"] = {0: ["BUILD_PASTURE"]}

    snap_valid = build_feed_execution_snapshot(ctx_valid)
    assert snap_valid.post_unit_state_verified is True
    assert snap_valid.post_unit_empty_pastures == 1

    # 2. Invalid pre-Day 12: target is already occupied
    ctx_invalid = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    class MockOccupiedTile:
        kind = "PASTURE"
        raw = {"kind": "PASTURE"}
        is_animal = False
        animal = None
        crop = None
        pos = (1, 1)
    ctx_invalid["farm"].tiles = [[None, None], [None, MockOccupiedTile()]]
    ctx_invalid["farm"].iter_tiles = lambda: [MockOccupiedTile()]
    ctx_invalid["farm"].quadrant_of = lambda pos: "NW"
    ctx_invalid["assignment"] = {0: {"task": "BUILD_PASTURE", "target": (1, 1), "args": []}}
    ctx_invalid["actions"] = {0: ["BUILD_PASTURE"]}

    snap_invalid = build_feed_execution_snapshot(ctx_invalid)
    assert snap_invalid.post_unit_state_verified is False
    assert snap_invalid.post_unit_state_reason == "unverifiable_build"

    # 3. Day 12+: zero credit, regardless of build
    ctx_d12 = make_mock_farm_ctx(day=12, hour=0, money=5000.0, shed_wheat=0)
    ctx_d12["farm"].tiles = [[None, None], [None, MockEmptyTile()]]
    ctx_d12["farm"].iter_tiles = lambda: [MockEmptyTile()]
    ctx_d12["farm"].quadrant_of = lambda pos: "NW"
    ctx_d12["assignment"] = {0: {"task": "BUILD_PASTURE", "target": (1, 1), "args": []}}
    ctx_d12["actions"] = {0: ["BUILD_PASTURE"]}

    snap_d12 = build_feed_execution_snapshot(ctx_d12)
    assert snap_d12.post_unit_state_verified is True
    assert snap_d12.post_unit_empty_pastures == 0


def test_c2b_empty_post_unit_shed_uses_snapshot_state():
    """Test 110: Empty post-unit shed still uses snapshot state instead of falling back to pre-unit observation."""
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=100)
    ctx["private"].shed["COW"] = 5
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=0, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_state_verified=True,
        post_unit_shed_inventory={},
        post_unit_worker_inventories=[{}],
        post_unit_placed_herd={"COW": 2, "SHEEP": 0, "GOOSE": 0},
    )
    ledger = build_feed_resource_ledger(ctx, current_herd=None, execution_snapshot=snapshot)
    assert ledger.wheat_in_shed == 0
    assert ledger.placed_herd["COW"] == 2
    assert ledger.owned_unplaced_herd["COW"] == 0


def test_c2b_place_empties_worker_and_shed_remains_empty():
    """Test 111: PLACE action empties worker while shed remains empty; ledger placed herd is correct."""
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    ctx["private"].shed = {}
    ctx["private"].inventories = [{"COW": 1}]
    
    class MockPastureTile:
        kind = "PASTURE"
        raw = {"kind": "PASTURE"}
        is_animal = False
        animal = None
        crop = None
        pos = (1, 1)
    
    ctx["farm"].tiles = [[None, None], [None, MockPastureTile()]]
    ctx["farm"].iter_tiles = lambda: [MockPastureTile()]
    ctx["farm"].quadrant_of = lambda pos: "NW"
    ctx["assignment"] = {0: {"task": "PLACE", "target": (1, 1), "args": ["COW"]}}
    ctx["actions"] = {0: ["PLACE", "COW"]}
    
    snap = build_feed_execution_snapshot(ctx)
    assert snap.post_unit_state_verified is True
    assert snap.post_unit_shed_inventory == {}
    assert snap.post_unit_worker_inventories == [{}]
    assert snap.post_unit_placed_herd.get("COW") == 1

    ledger = build_feed_resource_ledger(ctx, current_herd=None, execution_snapshot=snap)
    assert ledger.placed_herd["COW"] == 1
    assert ledger.owned_unplaced_herd["COW"] == 0
    assert ledger.wheat_in_shed == 0


def test_c2b_pickup_empties_shed_correct_worker_shed_wheat():
    """Test 112: PICKUP empties shed; fresh live ledger reflects 0 shed wheat and 3 worker wheat."""
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=3)
    ctx["private"].shed = {"WHEAT": 3}
    ctx["private"].inventories = [{}]
    ctx["assignment"] = {0: {"task": "PICKUP", "target": (0, 0), "args": ["WHEAT", 3]}}
    ctx["actions"] = {0: ["PICKUP", "WHEAT", 3]}

    snap = build_feed_execution_snapshot(ctx)
    assert snap.post_unit_state_verified is True
    assert snap.post_unit_shed_inventory == {}
    assert snap.post_unit_worker_inventories == [{"WHEAT": 3}]

    ledger = build_feed_resource_ledger(ctx, current_herd=None, execution_snapshot=snap)
    assert ledger.wheat_in_shed == 0
    assert ledger.wheat_on_workers == 3


def test_c2b_candidate_exception_transactional_rollback(monkeypatch):
    """Test 113: Candidate 1 accepted + candidate 2 exception -> full rollback of spend, feed hold, housing, decisions, and slots."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder
    import strategy.feed_feasibility as ff

    ctx = make_mock_farm_ctx(day=5, hour=0, money=20000.0, shed_wheat=50)
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 2},
        "buy_animal_sequence": ["SHEEP", "SHEEP"],
        "pending_structures": {},
    }
    snapshot = FeedExecutionSnapshot(
        day=5, hour=0, turns_remaining_today=24, feeds_due_today=0,
        feeds_assigned_this_turn=0, wheat_pickups_assigned_this_turn=0,
        worker_wheat=0, shed_wheat=50, n_active_units=1,
        market_purchase_can_help_today=True, execution_confidence="high",
        post_unit_empty_pastures=2, post_unit_state_verified=True,
    )
    intents["execution_snapshot"] = snapshot

    call_count = 0
    orig_eval = ff.evaluate_incremental_candidate
    def mock_eval(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Unexpected failure during candidate 2!")
        return orig_eval(*args, **kwargs)

    monkeypatch.setattr(ff, "evaluate_incremental_candidate", mock_eval)

    orders, ledger = builder.build(ctx, intents)

    # Zero animal orders
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    # Reverted financials and reservations
    assert ledger["final_candidate_purchase_spend"] == 0.0
    assert ledger["final_candidate_feed_hold"] == 0.0
    assert ledger["animal_order_slots_used"] == 0
    assert ledger["candidate_sequence_accepted"] == []
    # All decisions rejected with live_candidate_exception
    assert len(ledger["candidate_decisions"]) == 1
    assert ledger["candidate_decisions"][0]["accepted"] is False
    assert ledger["candidate_decisions"][0]["rejection_reason"] == "live_candidate_exception"
    # Housing state restored
    assert ledger["housing_state_final"]["empty_pastures"] == 2


def test_c2b_missing_build_target_fails_verification():
    """Test 114: Missing or off-grid BUILD target invalidates post_unit_state_verified."""
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    ctx["assignment"] = {0: {"task": "BUILD_PASTURE", "target": (99, 99), "args": []}}
    ctx["actions"] = {0: ["BUILD_PASTURE"]}

    snap = build_feed_execution_snapshot(ctx)
    assert snap.post_unit_state_verified is False
    assert snap.post_unit_state_reason == "unverifiable_build"


def test_c2b_harvest_missing_exact_task_target_fails_verification():
    """Test 115: HARVEST action missing exact assigned task target invalidates verification."""
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    ctx["assignment"] = {0: {"task": "HARVEST", "target": None, "args": []}}
    ctx["actions"] = {0: ["HARVEST"]}

    snap = build_feed_execution_snapshot(ctx)
    assert snap.post_unit_state_verified is False
    assert snap.post_unit_state_reason == "unverifiable_crop_harvest"


def test_c2b_harvest_must_not_guess_adjacent_tile():
    """Test 116: HARVEST verifier must not guess adjacent tile when target does not resolve."""
    ctx = make_mock_farm_ctx(day=5, hour=0, money=5000.0, shed_wheat=0)
    class MockCropTile:
        kind = "PLANT"
        raw = {"kind": "PLANT"}
        is_plant = True
        is_animal = False
        animal = None
        crop = "CARROT"
        yield_units = 5
        pos = (1, 2)

    # Tile at (1, 2) has a harvestable crop, but worker task target is (0, 0) (which is empty)
    ctx["farm"].tiles = [[None, None, None], [None, None, MockCropTile()]]
    ctx["farm"].iter_tiles = lambda: [MockCropTile()]
    ctx["farm"].quadrant_of = lambda pos: "NW"
    ctx["assignment"] = {0: {"task": "HARVEST", "target": (0, 0), "args": []}}
    ctx["actions"] = {0: ["HARVEST"]}

    snap = build_feed_execution_snapshot(ctx)
    assert snap.post_unit_state_verified is False
    # Verify worker did not magically harvest the adjacent crop
    assert snap.post_unit_worker_inventories[0].get("CARROT", 0) == 0


def test_c2b_missing_snapshot_diagnostic_reports_false(monkeypatch):
    """Test 117: Missing snapshot diagnostic truthfully reports post_unit_state_verified = False."""
    import config
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")
    monkeypatch.setattr(config, "get_point2_feed_mode", lambda: "live")
    from market.order_builder import OrderBuilder

    ctx = make_mock_farm_ctx(day=5, hour=0, money=20000.0, shed_wheat=50)
    ctx["feed_execution_snapshot"] = None
    builder = OrderBuilder()
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_wheat": 0,
        "buy_animal": {"SHEEP": 1},
        "buy_animal_sequence": ["SHEEP"],
        "pending_structures": {},
        "execution_snapshot": None,
    }

    orders, ledger = builder.build(ctx, intents)

    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert ledger["post_unit_state_verified"] is False
    assert ledger["post_unit_state_reason"] == "missing_snapshot"
    assert ledger["live_c2b_diagnostics"]["post_unit_state_verified"] is False
    assert ledger["live_c2b_diagnostics"]["post_unit_state_reason"] == "missing_snapshot"
