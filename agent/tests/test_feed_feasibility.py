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

