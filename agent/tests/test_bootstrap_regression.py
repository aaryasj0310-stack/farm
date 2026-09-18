"""Regression tests proving Arm A matches the frozen Point-2 baseline (08c494d).

Verifies:
1. Day-0 livestock candidate rejection under Point-2 live without bootstrap.
2. Production defaults remain shadow and none.
3. Day-0 market orders under Arm A match frozen baseline (zero animals admitted).
"""

import pytest
import config
from config import POINT2_FEED_MODE, BOOTSTRAP_LIVESTOCK_ARM
from strategy.feed_feasibility import FeedResourceLedger, evaluate_incremental_candidate
from state.state_tracker import reset_memory, get_state


def test_arma_rejects_day0_livestock():
    """Verify that under Arm A (bootstrap none), Point-2 live rejects Day 0 candidate for cash deficit."""
    ledger = FeedResourceLedger(
        day=0,
        hour=0,
        operational_horizon_days=4,
        observed_cash=3000.0,
        hard_cash_hold=1800.0,  # Turn commitments for seeds, reserve, hires
        wheat_in_shed=0,
        lifetime_price_policy="engine_stress_bound_v1",
    )
    # Full season funding: 25 days beyond operational horizon @ stress price = ~$900 + $400 buy = $1300 > $1200 avail
    res = evaluate_incremental_candidate(ledger, "COW", purchase_cost=400.0, is_day0_bootstrap=False)
    assert res.feasible is False
    assert res.blocking_reason in ("cash_deficit", "insufficient_cash")


def test_arma_config_defaults():
    """Verify default production configuration is shadow and none."""
    assert config.POINT2_FEED_MODE == "shadow"
    assert config.BOOTSTRAP_LIVESTOCK_ARM == "none"


def test_arma_day0_orders_match_frozen():
    """Verify market orders on Day 0 under Point-2 live with bootstrap none admit zero animals."""
    from kaggle_environments import make
    from state.observation_parser import parse_observation
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast
    from market.order_builder import OrderBuilder

    config.POINT2_FEED_MODE = "live"
    config.BOOTSTRAP_LIVESTOCK_ARM = "none"

    env = make("kaggriculture", configuration={"seed": 42, "season_duration": 30})
    env.reset()
    raw_obs = env.state[0].observation
    parsed = parse_observation(raw_obs)

    ctx = dict(parsed)
    ctx["point2_feed_mode"] = "live"
    fc = PriceForecast.load()
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)

    builder = OrderBuilder()
    orders, ledger = builder.build(ctx, plan.intents)

    # In Arm A (Point-2 live without bootstrap), zero animal purchase orders are admitted
    animal_orders = [o for o in orders if isinstance(o, (list, tuple)) and len(o) >= 2 and o[0] == "BUY_ANIMAL"]
    assert len(animal_orders) == 0

    # Reset config back to defaults
    config.POINT2_FEED_MODE = "shadow"
    config.BOOTSTRAP_LIVESTOCK_ARM = "none"


def test_stage2_capital_allocation_and_crop_floor():
    """Verify that Stage 2 allows real capital competition and preserves minimum crop floor."""
    import main
    from kaggle_environments import make

    config.POINT2_FEED_MODE = "live"
    config.BOOTSTRAP_LIVESTOCK_ARM = "ArmC"

    reset_memory()
    env = make("kaggriculture", configuration={"seed": 42, "season_duration": 30})
    env.reset()
    raw_obs = env.state[0].observation
    actions = main.agent(raw_obs)
    m_orders = actions.get("market", [])

    animal_orders = [o for o in m_orders if o[0] == "BUY_ANIMAL"]
    seed_orders = {o[1]: o[2] for o in m_orders if o[0] == "BUY_SEED"}

    # Arm C admits 2 COW + 1 SHEEP
    cow_orders = [o for o in animal_orders if o[1] == "COW"]
    sheep_orders = [o for o in animal_orders if o[1] == "SHEEP"]
    assert len(cow_orders) == 1 and cow_orders[0][2] == 2
    assert len(sheep_orders) == 1 and sheep_orders[0][2] == 1

    # Minimum crop floor is strictly preserved (>= 4 MELON, >= 4 WHEAT)
    assert seed_orders.get("MELON", 0) >= 4
    assert seed_orders.get("WHEAT", 0) >= 4

    config.POINT2_FEED_MODE = "shadow"
    config.BOOTSTRAP_LIVESTOCK_ARM = "none"


def test_stage2_candidate_rejection_preserves_previous():
    """Verify Arm D rejects Sheep #2 due to insufficient cash while preserving 2 COW + 1 SHEEP."""
    import main
    from kaggle_environments import make

    config.POINT2_FEED_MODE = "live"
    config.BOOTSTRAP_LIVESTOCK_ARM = "ArmD"

    reset_memory()
    env = make("kaggriculture", configuration={"seed": 42, "season_duration": 30})
    env.reset()
    raw_obs = env.state[0].observation
    actions = main.agent(raw_obs)
    m_orders = actions.get("market", [])

    animal_orders = [o for o in m_orders if o[0] == "BUY_ANIMAL"]
    cow_orders = [o for o in animal_orders if o[1] == "COW"]
    sheep_orders = [o for o in animal_orders if o[1] == "SHEEP"]

    assert len(cow_orders) == 1 and cow_orders[0][2] == 2
    assert len(sheep_orders) == 1 and sheep_orders[0][2] == 1  # Sheep 2 rejected, Sheep 1 preserved

    config.POINT2_FEED_MODE = "shadow"
    config.BOOTSTRAP_LIVESTOCK_ARM = "none"


def test_stage2_arm_e_three_cows():
    """Verify Arm E admits 3 COWs and displaces crop investment accordingly."""
    import main
    from kaggle_environments import make

    config.POINT2_FEED_MODE = "live"
    config.BOOTSTRAP_LIVESTOCK_ARM = "ArmE"

    reset_memory()
    env = make("kaggriculture", configuration={"seed": 42, "season_duration": 30})
    env.reset()
    raw_obs = env.state[0].observation
    actions = main.agent(raw_obs)
    m_orders = actions.get("market", [])

    animal_orders = [o for o in m_orders if o[0] == "BUY_ANIMAL"]
    assert len(animal_orders) == 1 and animal_orders[0][1] == "COW" and animal_orders[0][2] == 3

    seed_orders = {o[1]: o[2] for o in m_orders if o[0] == "BUY_SEED"}
    assert seed_orders.get("MELON", 0) >= 4
    assert seed_orders.get("WHEAT", 0) >= 4

    config.POINT2_FEED_MODE = "shadow"
    config.BOOTSTRAP_LIVESTOCK_ARM = "none"

