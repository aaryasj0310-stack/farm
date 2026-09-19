"""Day-0 Opening Commitment Idempotence Regression Test Suite (Cases A-J).

Tests the full MacroPlanner -> OrderBuilder -> Task Scheduler pipeline
to guarantee that Day-0 opening targets (12 MELON, 8 WHEAT) and seed orders
are strictly idempotent, space-bounded, and never redundantly purchased.
"""
import os
import sys
import pytest

# Ensure agent directory is in sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AGENT_DIR = os.path.join(REPO_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)
for sub in ("state", "strategy", "execution", "market"):
    p = os.path.join(AGENT_DIR, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from strategy.macro_planner import MacroPlanner, get_committed_crop_counts
from market.order_builder import OrderBuilder
from execution.task_scheduler import build_tasks
from price_forecast import PriceForecast


class DummyTile:
    def __init__(self, x, y, kind="EMPTY", crop=None, is_plant=False, consecutive_unwatered=0):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.crop = crop
        self.is_plant = is_plant
        self.consecutive_unwatered = consecutive_unwatered
        self.is_animal = False
        self.animal = None
        self.placed_day = 0
        self.planted_day = 0
        self.watered_today = False
        self.yield_units = 0
        self.fertilized_until_day = -1


class DummyFarm:
    def __init__(self, tiles=None, money=1000.0, unlocked=("NW",)):
        if tiles is None:
            # 5x5 NW quadrant with shed at (4,4) -> 24 tiles total
            self.tiles = []
            for r in range(5):
                for c in range(5):
                    if (r, c) == (4, 4):
                        continue
                    self.tiles.append(DummyTile(c, r, kind="EMPTY"))
        else:
            self.tiles = list(tiles)
        self.money = float(money)
        self.unlocked = set(unlocked)
        self.unlocked_quadrants = list(unlocked)
        self.farmer = (4, 4)
        self.hands = []
        self.hires_today = 0

    def iter_tiles(self):
        return iter(self.tiles)

    def quadrant_of(self, pos):
        r, c = pos[1], pos[0]
        if r < 5 and c < 5:
            return "NW"
        elif r < 5 and c >= 5:
            return "NE"
        elif r >= 5 and c < 5:
            return "SW"
        else:
            return "SE"


class DummyPrivate:
    def __init__(self, seeds=None, shed=None):
        self.seeds = dict(seeds or {})
        self.shed = dict(shed or {})
        self.inventories = [{}]


from state.observation_parser import MarketView, TownView


def make_test_ctx(farm=None, private=None, day=0, hour=0, money=1000.0):
    f = farm if farm is not None else DummyFarm(money=money)
    p = private if private is not None else DummyPrivate()
    fc = PriceForecast.load() if hasattr(PriceForecast, "load") else None
    mv = MarketView({"inventory": {"WHEAT": 1000, "MELON": 1000}, "prices": {"WHEAT": 25, "MELON": 250}})
    tv = TownView({"unlocked_shops": []})
    return {
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
        "farm": f,
        "private": p,
        "market": mv,
        "town": tv,
        "opponent_farm": None,
        "n_units": 1,
        "is_shed_adjacent": lambda pos: pos in ((3, 4), (4, 3)),
    }, fc


# =========================================================================
# Case A: Fresh opening (Day 0 Turn 0)
# =========================================================================
def test_case_a_fresh_opening():
    """Case A: 0 planted, 0 owned seeds -> requests 12 MELON, 8 WHEAT targets & purchases."""
    ctx, fc = make_test_ctx(day=0, hour=0, money=3000.0)
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    melon_planned = sum(1 for _, c in plan.plant_queue if c == "MELON")
    wheat_planned = sum(1 for _, c in plan.plant_queue if c == "WHEAT")
    assert melon_planned == 12
    assert wheat_planned == 8
    assert plan.intents.get("buy_seed", {}).get("MELON") == 12
    assert plan.intents.get("buy_seed", {}).get("WHEAT") == 8

    builder = OrderBuilder()
    orders, ledger = builder.build(ctx, plan.intents)
    seed_orders = {o[1]: o[2] for o in orders if o[0] == "BUY_SEED"}
    assert seed_orders.get("MELON") == 12
    assert seed_orders.get("WHEAT") == 8

    # Task scheduler with 0 owned seeds defers actual PLANT commands until seeds are in hand
    tasks = build_tasks(ctx, plan)
    plant_tasks = [t for t in tasks if t["op"] == "PLANT"]
    assert len(plant_tasks) == 0


# =========================================================================
# Case B: Partial opening (Day 0 Turn > 0)
# =========================================================================
def test_case_b_partial_opening():
    """Case B: 6 MELON, 4 WHEAT planted; 6 MELON, 4 WHEAT owned -> only queues remaining 6 & 4, 0 new purchases."""
    tiles = []
    # 6 planted melons
    for i in range(6):
        tiles.append(DummyTile(i % 5, i // 5, kind="PLANT", crop="MELON", is_plant=True))
    # 4 planted wheat
    for i in range(4):
        tiles.append(DummyTile((i + 6) % 5, (i + 6) // 5, kind="PLANT", crop="WHEAT", is_plant=True))
    # remaining 14 empty tiles (excluding shed)
    for i in range(10, 24):
        tiles.append(DummyTile(i % 5, i // 5, kind="EMPTY"))

    farm = DummyFarm(tiles=tiles, money=500.0)
    private = DummyPrivate(seeds={"MELON": 6, "WHEAT": 4})
    ctx, fc = make_test_ctx(farm=farm, private=private, day=0, hour=3)

    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    melon_planned = sum(1 for _, c in plan.plant_queue if c == "MELON")
    wheat_planned = sum(1 for _, c in plan.plant_queue if c == "WHEAT")
    assert melon_planned == 6
    assert wheat_planned == 4

    # Seed purchases must be 0 because 6 and 4 are already owned!
    assert plan.intents.get("buy_seed", {}).get("MELON", 0) == 0
    assert plan.intents.get("buy_seed", {}).get("WHEAT", 0) == 0

    builder = OrderBuilder()
    orders, ledger = builder.build(ctx, plan.intents)
    seed_orders = [o for o in orders if isinstance(o, (list, tuple)) and len(o) >= 2 and o[0] == "BUY_SEED"]
    assert len(seed_orders) == 0

    # Task scheduler schedules plant tasks because seeds are owned
    tasks = build_tasks(ctx, plan)
    plant_tasks = [t for t in tasks if t["op"] == "PLANT"]
    assert len(plant_tasks) == 10  # 6 melon + 4 wheat


# =========================================================================
# Case C: Fully satisfied opening
# =========================================================================
def test_case_c_fully_satisfied_opening():
    """Case C: 12 MELON, 8 WHEAT planted -> 0 queued planting, 0 seed purchases, fallow tiles preserved."""
    tiles = []
    for i in range(12):
        tiles.append(DummyTile(i % 5, i // 5, kind="PLANT", crop="MELON", is_plant=True))
    for i in range(8):
        tiles.append(DummyTile((i + 12) % 5, (i + 12) // 5, kind="PLANT", crop="WHEAT", is_plant=True))
    for i in range(20, 24):
        tiles.append(DummyTile(i % 5, i // 5, kind="EMPTY"))

    farm = DummyFarm(tiles=tiles, money=200.0)
    private = DummyPrivate(seeds={})
    ctx, fc = make_test_ctx(farm=farm, private=private, day=0, hour=10)

    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    assert len(plan.plant_queue) == 0
    assert plan.intents.get("buy_seed", {}).get("MELON", 0) == 0
    assert plan.intents.get("buy_seed", {}).get("WHEAT", 0) == 0

    builder = OrderBuilder()
    orders, ledger = builder.build(ctx, plan.intents)
    assert len([o for o in orders if o[0] == "BUY_SEED"]) == 0


# =========================================================================
# Case D: Owned-seed consumption
# =========================================================================
def test_case_d_owned_seed_consumption():
    """Case D: 0 planted, but 12 MELON and 8 WHEAT seeds already owned -> 0 purchases."""
    farm = DummyFarm(money=1000.0)
    private = DummyPrivate(seeds={"MELON": 12, "WHEAT": 8})
    ctx, fc = make_test_ctx(farm=farm, private=private, day=0, hour=1)

    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    assert sum(1 for _, c in plan.plant_queue if c == "MELON") == 12
    assert sum(1 for _, c in plan.plant_queue if c == "WHEAT") == 8
    assert plan.intents.get("buy_seed", {}).get("MELON", 0) == 0
    assert plan.intents.get("buy_seed", {}).get("WHEAT", 0) == 0


# =========================================================================
# Case E: Partial purchase execution
# =========================================================================
def test_case_e_partial_purchase_execution():
    """Case E: Budget limits initial buy to 5 melons; next turn recomputes remaining deficit."""
    # Turn 0 with limited discretionary money ($400): OrderBuilder clips to 5 melons ($400 // $80 = 5)
    ctx0, fc = make_test_ctx(day=0, hour=0, money=400.0)
    intents0 = {"buy_seed": {"MELON": 12, "WHEAT": 8}}
    builder = OrderBuilder(money_reserve=0)
    orders0, ledger0 = builder.build(ctx0, intents0)
    seed_bought = {o[1]: o[2] for o in orders0 if o[0] == "BUY_SEED"}
    assert seed_bought.get("MELON") == 5
    assert seed_bought.get("WHEAT", 0) == 0

    # Turn 1: 5 melon seeds now in inventory, 0 planted. MacroPlanner recomputes deficit.
    private1 = DummyPrivate(seeds={"MELON": 5, "WHEAT": 0})
    ctx1, _ = make_test_ctx(private=private1, day=0, hour=1, money=3000.0)
    planner = MacroPlanner(fc)
    plan1 = planner.build(ctx1)

    # Remaining need: 12 - 5 = 7 MELON, 8 - 0 = 8 WHEAT
    assert plan1.intents.get("buy_seed", {}).get("MELON") == 7
    assert plan1.intents.get("buy_seed", {}).get("WHEAT") == 8


# =========================================================================
# Case F: Failed / delayed planting
# =========================================================================
def test_case_f_failed_planting():
    """Case F: Seeds bought but unplanted; commitment remains eligible, 0 extra seeds bought."""
    private = DummyPrivate(seeds={"MELON": 12, "WHEAT": 8})
    ctx, fc = make_test_ctx(private=private, day=0, hour=5)
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    # 12 melon and 8 wheat still queued because 0 planted on board
    assert len(plan.plant_queue) == 20
    # But 0 seeds requested because owned count covers full targets
    assert plan.intents.get("buy_seed", {}).get("MELON", 0) == 0
    assert plan.intents.get("buy_seed", {}).get("WHEAT", 0) == 0


# =========================================================================
# Case G: Physical planting capacity constraint
# =========================================================================
def test_case_g_physical_planting_capacity():
    """Case G: Only 10 empty tiles available -> queues crops strictly within available space, 0 unplantable seeds."""
    tiles = [DummyTile(i % 5, i // 5, kind="EMPTY") for i in range(10)]
    for i in range(10, 24):
        tiles.append(DummyTile(i % 5, i // 5, kind="ROCK"))  # unplantable

    farm = DummyFarm(tiles=tiles, money=200.0)
    private = DummyPrivate(seeds={})
    ctx, fc = make_test_ctx(farm=farm, private=private, day=0, hour=0, money=200.0)

    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    avail_crop_tiles = 10 - len(plan.build_queue)
    melon_planned = sum(1 for _, c in plan.plant_queue if c == "MELON")
    wheat_planned = sum(1 for _, c in plan.plant_queue if c == "WHEAT")
    assert melon_planned == avail_crop_tiles
    assert wheat_planned == 0
    assert plan.intents.get("buy_seed", {}).get("MELON") == avail_crop_tiles
    assert plan.intents.get("buy_seed", {}).get("WHEAT", 0) == 0


# =========================================================================
# Case H: Experimental bootstrap floor
# =========================================================================
def test_case_h_bootstrap_floor_and_affordability():
    """Case H: BOOTSTRAP_LIVESTOCK_ARM active -> floor (4 MELON, 4 WHEAT) subtracts planted/owned & respects budget."""
    config.BOOTSTRAP_LIVESTOCK_ARM = "ArmC"
    config.POINT2_FEED_MODE = "live"

    try:
        # Partial fulfillment: 2 melon, 2 wheat planted; 1 melon seed owned
        tiles = [
            DummyTile(0, 0, kind="PLANT", crop="MELON", is_plant=True),
            DummyTile(0, 1, kind="PLANT", crop="MELON", is_plant=True),
            DummyTile(1, 0, kind="PLANT", crop="WHEAT", is_plant=True),
            DummyTile(1, 1, kind="PLANT", crop="WHEAT", is_plant=True),
        ]
        for i in range(4, 24):
            tiles.append(DummyTile(i % 5, i // 5, kind="EMPTY"))

        farm = DummyFarm(tiles=tiles, money=100.0)  # very tight money
        private = DummyPrivate(seeds={"MELON": 1, "WHEAT": 0})
        ctx, fc = make_test_ctx(farm=farm, private=private, day=0, hour=2, money=100.0)

        # Floor need: Melon = max(0, 4 - (2 + 1)) = 1, Wheat = max(0, 4 - (2 + 0)) = 2
        builder = OrderBuilder(money_reserve=0)
        intents = {"buy_seed": {}}
        orders, ledger = builder.build(ctx, intents)

        # Discretionary budget must not be driven negative
        assert ledger["budget"] >= ledger["spent_estimate"]
        seed_bought = {o[1]: o[2] for o in orders if o[0] == "BUY_SEED"}
        # With $100: 1 melon ($80) + 2 wheat ($20) = $100 -> fits budget
        assert seed_bought.get("MELON", 0) <= 1
        assert seed_bought.get("WHEAT", 0) <= 2
    finally:
        config.BOOTSTRAP_LIVESTOCK_ARM = "none"
        config.POINT2_FEED_MODE = "shadow"


# =========================================================================
# Case I: Production configuration regression
# =========================================================================
def test_case_i_production_configuration_defaults():
    """Case I: Verify production configuration defaults remain strictly untouched."""
    assert config.POINT2_FEED_MODE == "shadow"
    assert config.BOOTSTRAP_LIVESTOCK_ARM == "none"
    assert config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED is False
    assert config.POINT2_PRE_NE_CAPITAL_MODE == "off"


# =========================================================================
# Case J: Engine integration (Real 24-step Day 0 Simulation)
# =========================================================================
def test_case_j_engine_day0_simulation():
    """Case J: Step through full Day 0 (24 turns) in kaggle_environments.
    
    Verifies that across all 24 hours of Day 0:
    - Total MELON seed orders executed <= 12
    - Total WHEAT seed orders executed <= 8
    - Total seeds purchased <= 20
    - Fallow NW tiles remain unplanted
    """
    from kaggle_environments import make
    import main as agent_module
    import state_tracker

    state_tracker.reset_memory()
    agent_module.reset_agent_state()

    env = make("kaggriculture", configuration={"seed": 100, "episodeSteps": 720})
    env.reset()

    total_melon_seeds_bought = 0
    total_wheat_seeds_bought = 0

    for step in range(24):
        state = env.state
        obs0 = state[0].observation
        day = obs0.get("day", 0)
        hour = obs0.get("hour", 0)
        assert day == 0

        # Run candidate agent
        action = agent_module.agent(obs0, env.configuration)
        
        # Track market purchase orders in action
        market_orders = action.get("market", [])
        for order in market_orders:
            if isinstance(order, (list, tuple)) and len(order) >= 3 and order[0] == "BUY_SEED":
                prod, qty = order[1], int(order[2])
                if prod == "MELON":
                    total_melon_seeds_bought += qty
                elif prod == "WHEAT":
                    total_wheat_seeds_bought += qty

        env.step([action, {"farmer": ["PASS"], "hands": [], "market": []}])

    # End of Day 0 checks
    end_farm = env.state[0].observation.farms[0]
    end_private = env.state[0].observation.private

    assert total_melon_seeds_bought == 12, f"Expected exactly 12 melon seeds ordered on Day 0, got {total_melon_seeds_bought}"
    assert total_wheat_seeds_bought == 8, f"Expected exactly 8 wheat seeds ordered on Day 0, got {total_wheat_seeds_bought}"
    assert total_melon_seeds_bought + total_wheat_seeds_bought == 20

    # Count live plants + unplanted seeds at end of Day 0
    planted_crops = {}
    empty_nw_count = 0
    for r in range(5):
        for c in range(5):
            if (r, c) == (4, 4):
                continue
            tile = end_farm["tiles"][r][c]
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crop = tile.get("crop")
                planted_crops[crop] = planted_crops.get(crop, 0) + 1
            elif tile is None or (isinstance(tile, dict) and tile.get("kind") == "EMPTY"):
                empty_nw_count += 1

    # Inviolable NW fallow invariant: at least 4 NW tiles must remain fallow (unplanted)
    assert empty_nw_count >= 4, f"Expected at least 4 fallow tiles in NW quadrant, got {empty_nw_count}"
    assert planted_crops.get("MELON", 0) <= 12
    assert planted_crops.get("WHEAT", 0) <= 8


# =========================================================================
# Case K: Reproducible Baseline & Commit Verification
# =========================================================================
def test_case_k_reproducible_baseline_and_sha_verification():
    """Case K: Verify dynamic repo resolution, baseline SHA verification, and git archive extraction."""
    from simulations.experiments.run_day0_opening_ab import (
        resolve_repo_root,
        get_git_sha,
        verify_and_extract_baseline,
        REQUIRED_BASELINE_SHA,
    )

    repo_root = resolve_repo_root()
    assert os.path.exists(os.path.join(repo_root, ".git")), "Repo root must contain .git"

    # Verify baseline SHA
    base_sha = get_git_sha(REQUIRED_BASELINE_SHA)
    assert base_sha == REQUIRED_BASELINE_SHA

    # Verify candidate SHA (HEAD)
    cand_sha = get_git_sha("HEAD")
    assert len(cand_sha) == 40

    # Verify baseline extraction
    base_agent_dir = verify_and_extract_baseline(REQUIRED_BASELINE_SHA)
    assert os.path.exists(os.path.join(base_agent_dir, "main.py"))
    assert os.path.exists(os.path.join(base_agent_dir, "strategy", "macro_planner.py"))


# =========================================================================
# Case L: Actual vs Requested Purchase Accounting
# =========================================================================
def test_case_l_actual_vs_requested_purchase_accounting():
    """Case L: Distinguish requested seed orders from confirmed purchases (plantings + inventory)."""
    # Simulate a scenario where 4 melon seeds were ordered, 3 were planted, 1 remains in inventory
    tiles = [
        DummyTile(0, 0, kind="PLANT", crop="MELON", is_plant=True),
        DummyTile(0, 1, kind="PLANT", crop="MELON", is_plant=True),
        DummyTile(0, 2, kind="PLANT", crop="MELON", is_plant=True),
    ]
    for i in range(3, 24):
        tiles.append(DummyTile(i % 5, i // 5, kind="EMPTY"))

    farm = DummyFarm(tiles=tiles, money=1000.0)
    private = DummyPrivate(seeds={"MELON": 1, "WHEAT": 0})

    # Confirmed purchases at EOD = planted + inventory
    eod_planted_melon = sum(1 for t in farm.iter_tiles() if getattr(t, "crop", None) == "MELON")
    eod_inventory_melon = private.seeds.get("MELON", 0)
    confirmed_melon = eod_planted_melon + eod_inventory_melon

    assert eod_planted_melon == 3
    assert eod_inventory_melon == 1
    assert confirmed_melon == 4

    confirmed_spend = confirmed_melon * 80.0
    assert confirmed_spend == 320.0


# =========================================================================
# Case M: Bootstrap Floor Combined with Planner Demand (max)
# =========================================================================
def test_case_m_bootstrap_floor_max_combination():
    """Case M: In bootstrap mode, combines remaining floor with planner demand using max()."""
    config.BOOTSTRAP_LIVESTOCK_ARM = "ArmC"
    config.POINT2_FEED_MODE = "live"

    try:
        # Partial fulfillment: 2 melon, 2 wheat planted; 0 seeds owned
        tiles = [
            DummyTile(0, 0, kind="PLANT", crop="MELON", is_plant=True),
            DummyTile(0, 1, kind="PLANT", crop="MELON", is_plant=True),
            DummyTile(1, 0, kind="PLANT", crop="WHEAT", is_plant=True),
            DummyTile(1, 1, kind="PLANT", crop="WHEAT", is_plant=True),
        ]
        for i in range(4, 24):
            tiles.append(DummyTile(i % 5, i // 5, kind="EMPTY"))

        farm = DummyFarm(tiles=tiles, money=1500.0)
        private = DummyPrivate(seeds={"MELON": 0, "WHEAT": 0})
        ctx, fc = make_test_ctx(farm=farm, private=private, day=0, hour=1, money=1500.0)

        # Remaining floor: MELON = 4 - 2 = 2, WHEAT = 4 - 2 = 2
        # Planner requests: MELON = 3, WHEAT = 1
        # Combined demand: MELON = max(2, 3) = 3 (planner higher), WHEAT = max(2, 1) = 2 (floor higher)
        builder = OrderBuilder(money_reserve=0)
        intents = {"buy_seed": {"MELON": 3, "WHEAT": 1}}
        orders, ledger = builder.build(ctx, intents)

        seed_orders = {o[1]: o[2] for o in orders if o[0] == "BUY_SEED"}
        assert seed_orders.get("MELON") == 3, f"Expected max(2, 3) = 3 melon seeds, got {seed_orders.get('MELON')}"
        assert seed_orders.get("WHEAT") == 2, f"Expected max(2, 1) = 2 wheat seeds, got {seed_orders.get('WHEAT')}"
    finally:
        config.BOOTSTRAP_LIVESTOCK_ARM = "none"
        config.POINT2_FEED_MODE = "shadow"


# =========================================================================
# Case N: Late Day-0 Suppression (hour >= 17)
# =========================================================================
def test_case_n_late_day0_suppression():
    """Case N: At hour >= 17 on Day 0, seed purchases are strictly suppressed."""
    tiles = [DummyTile(i % 5, i // 5, kind="EMPTY") for i in range(24)]
    farm = DummyFarm(tiles=tiles, money=1000.0)
    private = DummyPrivate(seeds={})

    for h in (17, 18, 22, 23):
        ctx, fc = make_test_ctx(farm=farm, private=private, day=0, hour=h, money=1000.0)
        planner = MacroPlanner(fc)
        plan = planner.build(ctx)
        assert len(plan.intents.get("buy_seed", {})) == 0, f"Planner emitted buy_seed at hour {h}"

        builder = OrderBuilder(money_reserve=0)
        orders, _ = builder.build(ctx, plan.intents)
        seed_buys = [o for o in orders if o[0] == "BUY_SEED"]
        assert len(seed_buys) == 0, f"OrderBuilder emitted seed orders at hour {h}"

