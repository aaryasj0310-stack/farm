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
"""

import copy
import json
import os
import subprocess
import sys
from unittest.mock import MagicMock
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


def make_mock_tile(pos, kind="EMPTY", is_plant=False, is_animal=False, animal=None, crop=None, placed_day=0):
    t = MagicMock()
    t.pos = pos
    t.kind = kind
    t.is_plant = is_plant
    t.is_animal = is_animal
    t.animal = animal
    t.crop = crop
    t.placed_day = placed_day
    t.watered_today = True
    t.fed_today = False
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
        tiles.append(make_mock_tile((i, 0), kind="PASTURE", is_animal=True, animal=a, placed_day=day - 2))

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
    farm.unlocked = list(unlocked)
    farm.farmer = (4, 4)
    farm.hands = [(4, 4)]
    farm.iter_tiles = MagicMock(return_value=tiles)
    farm.quadrant_of = MagicMock(return_value="NW")

    shed_dict = {"WHEAT": shed_wheat}
    shed_dict.update(shed_animals)
    private = MagicMock()
    private.shed = shed_dict
    private.inventories = worker_animals if worker_animals else [{}]
    private.seeds = {}

    market = MagicMock()
    # Inventory 10000 gives normal base price (~25)
    market.inventory = {"WHEAT": 10000, "COW": 5, "SHEEP": 5, "GOOSE": 5}

    ctx = {
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farm": farm,
        "private": private,
        "market": market,
        "town": {"shops": {}},
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
    # Day 10, Hour 23, 0 wheat in shed/workers, 1 placed COW that needs feed today
    ctx = make_mock_farm_ctx(day=10, hour=23, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    # Check snapshot: turns_remaining == 1 (hour 23), market cannot help today
    snapshot = ledger.execution_snapshot
    assert snapshot is not None
    assert snapshot.hour == 23
    assert snapshot.turns_remaining_today == 1
    assert snapshot.market_purchase_can_help_today is False

    # Evaluate existing herd feasibility: must fail because today cannot be fed
    feasible, res = evaluate_existing_herd_feasibility(ledger)
    assert feasible is False
    assert res.blocking_day == 10
    assert res.blocking_reason is not None


def test_timing_hour0_market_purchase_can_help_later_turns():
    """At Hour 0, market purchases can help subsequent turns today if funds exist."""
    # Day 10, Hour 0, 0 wheat in shed, 1 placed COW, $1000 money
    ctx = make_mock_farm_ctx(day=10, hour=0, money=1000.0, shed_wheat=0, placed_animals=["COW"])
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    snapshot = ledger.execution_snapshot
    assert snapshot is not None
    assert snapshot.hour == 0
    assert snapshot.market_purchase_can_help_today is True

    feasible, res = evaluate_existing_herd_feasibility(ledger)
    # Even with 0 wheat initially, $1000 can buy market wheat for today and operational horizon
    assert feasible is True
    assert res.near_term_market_wheat_required > 0
    assert ledger.existing_feed_cash_hold > 0.0


# ===========================================================================
# 3. Placed Herd vs Owned Unplaced Herd Semantics
# ===========================================================================

def test_placed_vs_owned_unplaced_herd_semantics():
    """Placed herd eats today; owned unplaced herd does not eat today but has future funding liability."""
    # 0 placed animals, but 2 cows in shed. Day 10, Hour 23. 0 wheat.
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
    # Should NOT fail for today's feed because unplaced cows do not eat today
    # But they create a future funding liability
    assert feasible is True
    assert ledger.existing_feed_cash_hold > 0.0
    # Lifetime days = 28 - 10 = 18 days per cow * 2 cows = 36 wheat * price (~25) = ~900
    assert ledger.existing_feed_cash_hold >= 36 * 20.0


# ===========================================================================
# 4. No Speculative Resources & Zero Revenue Credit
# ===========================================================================

def test_candidate_zero_revenue_credit():
    """Candidate evaluation must NOT assume revenue from animal products to fund its own feed."""
    # Day 10, Hour 0. 0 placed animals. Money = $450.
    # COW purchase cost = $400.
    # Remaining lifetime feed for COW = (28 - 10) * 1 = 18 wheat * $25 = $450.
    # Total required cash = $400 (cost) + $450 (feed) = $850.
    # With only $450 money, cow purchase must be rejected despite prospective milk revenue ($60/day).
    ctx = make_mock_farm_ctx(day=10, hour=0, money=450.0, shed_wheat=0, placed_animals=[])
    ledger = build_feed_resource_ledger(ctx, hard_cash_hold=0.0, strategic_cash_hold=0.0)

    res = evaluate_incremental_candidate(ledger, "COW")
    assert res.feasible is False
    assert res.blocking_reason in ("insufficient_cash", "insufficient_operational_feed")


# ===========================================================================
# 5. Sequential Non-Reused Reservations & Monotonicity
# ===========================================================================

def test_sequential_reservations_do_not_double_spend():
    """Adding candidate 1 reduces available cash; candidate 2 can only spend what remains."""
    # Money = $1,100.
    # Cow: cost $400, feed 19 * $25 = $475. Total cow = $875.
    # Sheep: cost $300, feed 19 * $25 = $475. Total sheep = $775.
    # Money $1,100 is enough for ONE cow ($875), leaving $225.
    # $225 is NOT enough for sheep ($775).
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
    # Evaluate with $700 (rejected because cow needs ~$875)
    ctx_700 = make_mock_farm_ctx(day=10, hour=0, money=700.0, shed_wheat=0, placed_animals=[])
    ledger_700 = build_feed_resource_ledger(ctx_700)
    res_700 = evaluate_incremental_candidate(ledger_700, "COW")
    assert res_700.feasible is False

    # Evaluate with $500
    ctx_500 = make_mock_farm_ctx(day=10, hour=0, money=500.0, shed_wheat=0, placed_animals=[])
    ledger_500 = build_feed_resource_ledger(ctx_500)
    res_500 = evaluate_incremental_candidate(ledger_500, "COW")
    assert res_500.feasible is False


def test_existing_herd_infeasible_blocks_all_candidates():
    """If the existing herd is already infeasible, no candidate can be feasible."""
    # Existing cow with zero wheat and zero cash at hour 23
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
    # Plentiful wheat and cash, but suppose animal output prices are worthless
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
    # Initialize empty tiles in NW
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
